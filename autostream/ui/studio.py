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
      <button type="button" class="btn btn-primary" data-act="studio-gd-open" id="studio-gd-open">Make a reel</button>
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
          <!-- WHERE THE REEL STANDS, in one word, always in view: Changed, Timing stale, Planning,
               Ready to render, Rendering, Rendered or Check failed. The title says why. -->
          <span class="studio-badge" id="studio-badge" role="status" aria-live="polite"></span>
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
          <!-- BESIDE THE RENDER IT HOLDS UP: while the kill timing is stale Render waits, and the way to
               un-stale it is right here, in the accent, where the hand already is. -->
          <button type="button" class="btn btn-primary studio-attn hide" data-act="studio-flow" data-do="replan"
                  id="studio-tl-replan">Replan for this section</button>
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
               because "a bit higher than the minimap" is a place you
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
        <!-- THREE WAYS TO UPDATE THE REEL, not one "Rebuild" that might mean any of them: each says
             what it keeps and what it changes before it runs (studio_flowAsk). -->
        <div class="studio-acts3" role="group" aria-label="Update the reel">
          <span class="muted studio-small">Update the reel:</span>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-flow-ask" data-do="rerender">Re-render</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-flow-ask" data-do="retime">Re-time</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-flow-ask" data-do="replan">Replan&hellip;</button>
        </div>
        <!-- THE RENDER NOBODY HAS TO ASK FOR. A couple of seconds after the
             last edit the real render starts by itself, so the finished video
             is usually there by the time the preview has been watched. The
             same setting as Settings > Clips; see studio_autoGo. -->
        <div class="studio-auto">
          <label class="studio-check"><input type="checkbox" id="studio-auto-render" checked> Render in the background</label>
          <span class="studio-auto-state" id="studio-auto-state" role="status" aria-live="polite"></span>
        </div>
      </div>
      <!-- The reel's timing, when it is stale, and whatever is being worked out for it: the same banner
           as the Song tab's, so it is wherever the player is looking (studio_flowDraw). -->
      <div class="studio-flow-host hide" id="studio-tl-stale"></div>

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
      <!-- WHEN THE PART, THE SONG, THE MARKS OR THE DROPS NO LONGER MATCH THE PLAN: said here, at the
           top, in words nobody can miss, with the way to resolve it -- studio_flowDraw. Nothing is
           re-planned or re-timed until the player picks one. -->
      <div class="studio-flow-host" id="studio-sg-stale"></div>
      <p class="field-label">The whole song &mdash; drag the lit-up part to move it, or its edges to resize.
        The faint lines are the beat; bright ones start a bar. The kill marks stay where they are on the
        song: moving the part never moves them.</p>
      <canvas class="studio-sg-wave" id="studio-sg-overview" height="90" aria-label="Whole song"></canvas>
      <p class="field-label">The part you picked, up close, on its own beats &mdash; click to hear it from there,
        double-click to mark a kill (or a drop, on the top lane), drag a mark to move it</p>
      <canvas class="studio-sg-wave studio-sg-detail" id="studio-sg-detail" height="140"
              aria-label="The chosen part: drops along the top, kills below. Click a mark to select it, drag to move it, double-click to add or remove"></canvas>
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
      <!-- NO "USE THIS PART" ANY MORE. Every change here is already on the reel, as an edit undo can
           take back; what it does to the kill timing is the banner's to resolve, by the player. -->
      <div class="studio-sg-apply">
        <span class="muted" id="studio-sg-msg">A change here is on the reel at once, and undo takes it back. A part,
          song or marks the kills are not timed for yet are said above, with how to update them.</span>
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
    <!-- the Song step's player: here, not in the step, so redrawing the step does not stop the song -->
    <audio id="studio-gd-audio" preload="metadata"></audio>
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
      <!-- FROM THE STEPS, BACK TO THE STEPS: All settings is the same draft seen fuller, and this goes
           back to the step it came from with everything chosen here kept (studio_mkToGuide). -->
      <button type="button" class="btn btn-ghost hide" data-act="studio-mk-guide" id="studio-mk-guide">&larr; Back to the steps</button>
      <div class="mk-head-text">
        <h2 class="mk-title" id="studio-make-title">Make a reel</h2>
        <p class="muted" id="studio-make-facts"></p>
      </div>
      <span class="studio-badge" id="studio-mk-badge" role="status" aria-live="polite"></span>
    </header>
    <div class="mk-layout">
      <!-- THE SETTINGS BY WHAT THEY ARE FOR. They were grouped by where each had been added: the drops
           in Kills, the intro under the song, Headshots only under Shape. Now Music is the song, its part
           and its drops; Footage the clips and what is built from them; Timing where each kill lands,
           how long and in what order; Look the picture. Each control says in a line what changing it
           does -- the same words the timeline's table uses (studio_mkSaysDraw). -->
      <nav class="mk-nav" id="studio-mk-nav" aria-label="Sections of this page">
        <button type="button" class="mk-nav-b is-on" data-act="studio-mk-jump" data-sec="style">Style</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="music">Music</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="footage">Footage</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="timing">Timing</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="look">Look</button>
      </nav>
      <div class="mk-body">
        <section class="mk-sec" id="mk-sec-style">
      <h3 class="studio-h">Style <span class="muted studio-small" id="studio-style-count"></span></h3>
      <p class="mk-says" data-change="style"></p>
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
        <section class="mk-sec" id="mk-sec-music">
      <h2 class="mk-group">Music</h2>
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
        <p class="mk-says" data-change="part"></p>
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
      <div class="studio-mk-dropsbox hide" id="studio-mk-dropsbox">
        <h3 class="studio-h">Drops <span class="muted studio-small">where the bass comes in</span></h3>
        <p class="mk-says" data-change="drop"></p>
        <div class="field-inline">
          <button type="button" class="btn btn-sm" data-act="studio-mk-adddrop" title="Marks a bass drop at the playhead (D)">Mark a drop here <kbd>D</kbd></button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-cleardrops" id="studio-mk-cleardrops">Drops back to automatic</button>
          <span class="muted studio-small">They are drawn on the top lane of the kills, below, and on the song above.</span>
        </div>
        <ol class="studio-mk-marklist studio-mk-droplist" id="studio-mk-droplist" aria-label="Drops"></ol>
      </div>
        </section>
        <section class="mk-sec" id="mk-sec-footage">
      <h2 class="mk-group">Footage</h2>
      <p class="mk-says" data-change="clips"></p>
      <div class="field-inline">
        <span id="studio-mk-clips"></span>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-make-cancel">Change the clips</button>
      </div>
      <!-- THE CLIP A BUILD AND DROP REEL BUILDS ON, chosen here as it is on the guide's Clips step. -->
      <div class="hide" id="studio-mk-buildrow">
        <label class="field-label" for="studio-mk-build">The build: the clip the reel builds into the drop with</label>
        <select class="select" id="studio-mk-build"></select>
      </div>
      <!-- THE INTRO, HERE AND NOT ONLY ON THE TIMELINE. It used to be
           reachable only after a reel had been rendered once, so the first
           render always went out without one. The trim and the fit stay on the
           timeline's own dialog; what belongs here is which clip and whether
           it is heard, because those are the two that change the render. -->
      <div class="studio-mk-intro hide" id="studio-mk-intro">
        <h3 class="studio-h">Intro clip</h3>
        <p class="mk-says" data-change="intro"></p>
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
      <!-- Valorant clips carry a headshot reading per kill; shown only when some do. -->
      <label class="studio-check hide" id="studio-hs-row"><input type="checkbox" id="studio-hs-only">
        Headshot kills only <span class="muted studio-small" id="studio-hs-note"></span></label>
        </section>
        <section class="mk-sec" id="mk-sec-timing">
      <h2 class="mk-group">Timing</h2>
      <!-- M4: THE KILLS, EDITABLE HERE. The Song tab lets you mark where each kill lands; this
           is the same editor before the reel exists. "Show where the kills will land" plans the
           reel the way Build would and draws every kill on the song; touch one and it becomes
           yours, and Build puts the rest around it. -->
      <div class="studio-mk-kills hide" id="studio-mk-killsbox">
        <h3 class="studio-h">Kills <span class="muted studio-small">where each one lands on the song</span></h3>
        <p class="mk-says" data-change="mark"></p>
        <!-- The part moved, or the drops, since the kills drawn were planned: said here, with the fix. -->
        <div class="studio-flow-host hide" id="studio-mk-stale"></div>
        <p class="muted studio-small" id="studio-mk-killnote"></p>
        <div class="field-inline">
          <button type="button" class="btn btn-sm" data-act="studio-mk-plan" id="studio-mk-plan">Show where the kills will land</button>
          <button type="button" class="btn btn-sm" data-act="studio-mk-addmark" title="Drops a kill at the playhead, exactly where it is (K)">Mark a kill here <kbd>K</kbd></button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-clearmarks" id="studio-mk-clearmarks">Back to automatic</button>
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
        <ol class="studio-mk-marklist" id="studio-mk-marklist" aria-label="Kills"></ol>
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
      <p class="mk-says" data-change="length"></p>
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
        </section>
        <section class="mk-sec" id="mk-sec-look">
      <h2 class="mk-group">Look</h2>
      <h3 class="studio-h">Shape</h3>
      <p class="mk-says" data-change="framing"></p>
      <div class="field-inline studio-shape">
        <div class="seg" role="group" aria-label="Format">
          <button type="button" class="seg-btn is-active" data-act="studio-fmt" data-fmt="landscape">Landscape 16:9</button>
          <button type="button" class="seg-btn" data-act="studio-fmt" data-fmt="vertical">Vertical 9:16</button>
        </div>
        <!-- HOW A 16:9 GAME FILLS A 9:16 FRAME: cropped to its middle, all of it over a
             blurred copy, or -- the default since v1.80.0, the player's choice -- the middle
             three quarters, a third taller. Only asked when it is a question. -->
        <div class="seg hide" role="group" aria-label="Vertical framing" id="studio-mk-fit">
          <button type="button" class="seg-btn is-active" data-act="studio-mk-fit" data-fit="near">Near fit</button>
          <button type="button" class="seg-btn" data-act="studio-mk-fit" data-fit="fit">Fit the whole picture</button>
          <button type="button" class="seg-btn" data-act="studio-mk-fit" data-fit="zoom">Zoom to fill</button>
        </div>
      </div>
      <!-- THE TEMPLATE: what the style picked, shown part by part with its
           example, and changeable one drawer at a time. -->
      <h3 class="studio-h">Template</h3>
      <p class="mk-says" data-change="look"></p>
      <div class="bin-dealer">
        <button type="button" class="btn btn-sm" data-act="studio-deal">Deal a template</button>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-deal-reset">Back to the style's own</button>
        <span class="bin-code" id="studio-deal-code"></span>
      </div>
      <p class="muted studio-small hide" id="studio-fast-note" role="note"></p>
      <div class="bin-hand" id="studio-hand"></div>
      <!-- THE SONG'S WORDS, here as on the guide's Look step: they rode in from the steps but could not be
           seen or changed on this page. Used if the song's lyrics are found when it renders. -->
      <div id="studio-mk-lyricsrow">
        <h3 class="studio-h">Lyrics</h3>
        <p class="mk-says" data-change="lyrics"></p>
        <div class="seg" role="group" aria-label="Lyrics" id="studio-mk-lyrics"></div>
      </div>
        </section>
      </div>
    </div>
    <div class="gd-chip" id="studio-mk-chip" role="status" hidden></div>
    <div class="mk-bar">
      <label class="field-label mk-bar-name" for="studio-name">Name</label>
      <input class="input mk-bar-input" id="studio-name" maxlength="80" placeholder="Montage reel">
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
      <p class="muted studio-yt-hint">Only the song's audio is downloaded, into <span class="mono" id="studio-yt-folder">Videos\AutoStream\songs</span>,
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
       name or a code ("shake", "K02"). A dropdown of "K02 · Shake" lines, or
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
             placeholder="Search by name or code, e.g. shake or K02">
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
    <div class="modal-body"><video id="studio-preview-video" controls playsinline preload="metadata"></video>
      <!-- Where the kills are along the clip, placed from the clip's own length in the library
           rather than the element's duration, which is NaN until the metadata lands. -->
      <div class="gd-pvmarks hide" id="studio-preview-marks"></div></div>
    <div class="modal-actions">
      <span class="media-knobs" data-for="studio-preview-video"></span>
      <!-- Opened from the guide's Clips step: the clip is chosen or taken out from here. -->
      <button type="button" class="btn btn-primary hide" id="studio-preview-pick" data-act="studio-gd" data-gd="pv-pick"></button>
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
  style: '', song: '', songShape: null, fmt: 'landscape', vfit: 'near', order: 'chosen',
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
  /* THE TIMING DRAFT OF THE REEL ON THE TIMELINE, read from its project (studio_sgSync); the same
     shape as studio.mk below, so one machinery edits both. */
  sg: {song: '', shape: null, start: 0, end: 0, hand: [], edited: false, planned: null, drops: null,
       drag: null, ticked: {}, ac: null, sel: {}, nid: 0, markDrag: null, boxSel: null},
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
    /* The map and the game mode of the match it was cut from, when the run has the record:
       the guide's clip browser filters by both. A clip outside every match has neither. */
    const m = c.match === undefined ? null : (f.matches || [])[c.match];
    if (m) { c.map = m.map || ''; c.mode = m.mode || ''; }
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
    '<div class="studio-band-who"><strong>' + (ad.mode === 'pool' ? 'Adding to ' + esc(ad.name) + '\u2019s pool'
      : ad.mode === 'replace' ? 'A new clip for ' + esc(studio_shotName(ad.shot)) + ' of ' + esc(ad.name) : 'Adding to ' + esc(ad.name)) + '</strong>' +
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
    (ad.mode === 'pool'
      ? '<button type="button" class="btn btn-sm btn-primary" data-act="studio-add-go">Add the picked clips to the pool</button>'
      : ad.mode === 'replace'
        ? '<button type="button" class="btn btn-sm btn-primary" data-act="studio-add-go">Use the picked clip for ' + esc(studio_shotName(ad.shot)) + '</button>'
        : '<button type="button" class="btn btn-sm" data-act="studio-make">Replan ' + esc(ad.name) + ' with these clips</button>') +
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
  const nPick = studio.selected.length;
  studio_el('studio-make-btn').textContent = !ad ? 'Make a reel'
    : ad.mode === 'pool' ? 'Add ' + nPick + (nPick === 1 ? ' clip' : ' clips') + ' to the pool'
    : ad.mode === 'replace' ? 'Use this clip for ' + studio_shotName(ad.shot)
    : 'Replan ' + ad.name + ' with these clips';
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
  studio.gd.pv = null;                     /* the library's preview: nothing to choose in it */
  studio_pvMarks(c);
  studio_show('studio-preview-pick', false);
  studio_show('studio-preview-scrim', true);
  v.play().catch(() => {});
}
/* THE KILLS ALONG THE CLIP, each a mark that seeks to it: a headshot in the warn colour. Placed
   by the library's own length -- `duration` on the element is NaN until its metadata is read. */
function studio_pvMarks(c) {
  const box = studio_el('studio-preview-marks'), dur = Number(c.duration) || 0, ks = c.kills || [];
  if (!box) return;
  box.innerHTML = dur > 0 && ks.length ? ks.map((k, i) => {
    const hs = (c.hs || [])[i] === true;
    return '<button type="button" class="gd-pvmark' + (hs ? ' is-hs' : '') + '" style="left:' + Math.min(100, Math.max(0, k / dur * 100)).toFixed(2) +
      '%" data-act="studio-gd" data-gd="pv-seek" data-t="' + Number(k).toFixed(2) + '" title="Kill ' + (i + 1) + ' at ' + studio_secs(k) +
      (hs ? ', a headshot' : '') + '" aria-label="Kill ' + (i + 1) + ' at ' + studio_secs(k) + '"></button>';
  }).join('') + '<i class="gd-pvhead" id="studio-preview-head"></i>' : '';
  box.classList.toggle('hide', !(dur > 0 && ks.length));
}
/* Closing the preview. Opened from the guide it closes alone: the guide under it stays on its
   step, its slot and its page, with every choice as it was. Anywhere else it is one of the
   modals Close and Escape put away together. */
function studio_previewClose() {
  if (!studio.gd.pv) return studio_closeModals();
  const v = studio_el('studio-preview-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  studio.gd.pv = null;
  studio_show('studio-preview-scrim', false);
}

function studio_closeModals() {
  if (studio.fxp) studio_fxpClose();
  const v = studio_el('studio-preview-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  const a = studio_el('studio-mk-audio');
  if (a && !a.paused) a.pause();
  const ga = studio_el('studio-gd-audio');
  if (ga && !ga.paused) ga.pause();
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

async function studio_openMake(opts) {
  const o = opts || {};
  if (!studio.selected.length) return;
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  const ad = studio.adding;
  studio_el('studio-make-facts').textContent = sel.length + ' clips, ' +
    sel.reduce((n, c) => n + studio_killsOf(c), 0) + ' kills. Every cut and kill lands on the beat; ' +
    'you can change anything on the timeline afterwards.' +
    (ad ? ' Replanning ' + ad.name + ' plans every shot again' +
      (ad.edited ? ', so the edits you made on its timeline are replaced on shots the new plan does not keep.' : '.') +
      ' It keeps the song, the part, your own kill marks and drops, and the reel\u2019s look; undo brings the reel back as it was.' : '');
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
  studio_el('studio-make-title').textContent = ad ? 'Replan ' + ad.name : 'Make a reel';
  studio_el('studio-build-btn').textContent = ad ? 'Replan and render' : 'Build and render';
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
    /* THE PLAYER'S OWN MARKS GO WITH A REBUILD: their whole list when they had edited it, else the marks
       they placed, as constraints the plan keeps (editflow.merge_anchors). */
    studio.mk.planned = null; studio.mk.sel = {};
    studio.mk.of = ad.output || 'reel';      /* this draft is that reel's now; see studio_gdOpen */
    if (ad.marks && ad.marks.length) {
      const own = ad.anchors || [];
      studio.mk.hand = ad.marks.map((t, i) => ({id: 'h' + i, t: t, auto: !own.some(a => Math.abs(a - t) < 0.002), name: ''}));
      studio.mk.edited = true; studio.mkAnchors = null;
    } else {
      studio.mk.hand = []; studio.mk.edited = false;
      studio.mkAnchors = (ad.anchors || []).length ? ad.anchors.slice() : null;
    }
    if (ad.song && studio.songShape) {
      studio.mk.mode = 'part'; studio.mk.touched = !ad.part_auto;
      /* a part the page drew is drawn again (studio_mkDefault, below), as a length; one the
         player chose is theirs, to its end */
      if (!ad.part_auto) { studio.mk.start = ad.start; studio.mk.end = Math.max(ad.start + studio_mkBar(), ad.end); }
      if (ad.drops) {
        studio.mk.drops = ad.drops.map(t => { studio.mk.nid = (studio.mk.nid || 0) + 1; return {id: 'u' + studio.mk.nid, t: t, auto: false}; });
      }
    }
    /* What the reel asked for, so a rebuild is the same kind of reel. */
    studio.fill = ad.fill || '';
    studio.keepAll = !!ad.keep_all;
    studio.buildClip = ad.build_clip || '';
    studio.mkIntro = ad.intro_clip ? {path: ad.intro_clip.path, audio: ad.intro_clip.audio} : {path: '', audio: false};
    const hsBox = studio_el('studio-hs-only');
    if (hsBox) hsBox.checked = !!ad.hs_only;
    studio.mkKeep = null;                  /* the reel's own lyrics ride in ad.keep */
  } else if (!o.fromGuide) {
    studio.mkKeep = null;                  /* the guide's lyrics go with the guide's hand-over only */
    studio.mkAnchors = null;
  }
  if (!o.fromGuide) studio.mkFrom = null;
  studio_show('studio-mk-guide', !!studio.mkFrom);
  const mkFacts = studio_el('studio-make-facts');
  if (studio.mkKeep && studio.mkKeep.lyrics && mkFacts) {
    const look = studio_gdLyricLooks().find(l => l.key === studio.mkKeep.lyrics.look);
    mkFacts.textContent += ' Lyrics: ' + (look ? look.label : studio.mkKeep.lyrics.look) + ', from the steps, if the song’s lyrics are found.';
  }
  /* drawn again from what is now chosen: a rebuild's or the guide's, not the page's last */
  document.querySelectorAll('#studio-make [data-act="studio-fmt"]').forEach(x =>
    x.classList.toggle('is-active', x.getAttribute('data-fmt') === studio.fmt));
  document.querySelectorAll('#studio-make [data-act="studio-mk-fit"]').forEach(x =>
    x.classList.toggle('is-active', x.getAttribute('data-fit') === studio.vfit));
  studio_mkIntroDraw();
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
  studio_mkSaysDraw();
  studio_mkFootageDraw();
  studio_mkChip();
  studio_mkFlowDraw();
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
  /* Changed until the verdict is asked, Planning while it is: the badge says which. */
  studio.mkVerdict = null; studio.mkAsking = 'waiting';
  studio_mkBadge();
  studio.mkChipTimer = setTimeout(async () => {
    studio.mkAsking = 'asking';
    studio_mkBadge();
    const got = await API.post('/api/studio/feasible', studio_planBody(false)).catch(() => null);
    if (ticket !== studio.mkChipAsk) return;
    studio.mkAsking = '';
    if (!got || !got.ok) { studio_mkBadge(); return; }
    const v = got.verdict, label = {ok: 'Works', warn: 'Will work, but', bad: "Won't work"}[v.level];
    studio.mkVerdict = v;
    const act = {'pick-song': 'Choose another song above.', 'pick-clips': 'Go back and pick more clips.',
                 'format:vertical': '', 'style:drop': 'Choose Build and drop above.',
                 'part:fit': 'Shorten the part under Music, or pick a longer build clip.'}[v.fix] || '';
    el.className = 'gd-chip ' + v.level;
    el.innerHTML = '<span class="gd-dot">' + label + '</span><p>' + esc(v.text) + (act ? ' ' + esc(act) : '') + '</p>' +
      (v.fix === 'format:vertical' ? '<button type="button" class="btn btn-primary btn-sm" data-act="studio-mk-chipfix">Use 9:16</button>' : '<span></span>');
    el.hidden = false;
    studio_mkBadge();
  }, 300);
}

/* WHAT EACH CONTROL DOES TO A REEL, in a line, from the table the timeline answers from
   (clips/editflow.py): "re-renders only", "plans the reel again"... */
function studio_mkSaysDraw() {
  const rows = studio_flowTable().changes || [];
  document.querySelectorAll('#studio-make .mk-says[data-change]').forEach(el => {
    const r = rows.find(x => x.key === el.getAttribute('data-change'));
    el.textContent = r ? r.says : '';
  });
}

/* FOOTAGE AND LOOK, drawn from what is chosen: the clips, the build clip a Build and drop reel builds
   on, and the lyrics' look -- which rode in from the steps but could not be seen or changed here. */
function studio_mkFootageDraw() {
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  const box = studio_el('studio-mk-clips');
  if (box) box.textContent = sel.length + (sel.length === 1 ? ' clip, ' : ' clips, ') +
    sel.reduce((n, c) => n + studio_killsOf(c), 0) + ' kills';
  const drop = studio.style === 'drop';
  studio_show('studio-mk-buildrow', drop && sel.length > 0);
  const bs = studio_el('studio-mk-build');
  if (bs && drop) {
    bs.innerHTML = '<option value="">The best of them, chosen by AutoStream</option>' + sel.map(c =>
      '<option value="' + esc(c.path) + '"' + (c.path === studio.buildClip ? ' selected' : '') + '>' +
      esc((c.name || c.id) + ' · ' + studio_killsOf(c) + (studio_killsOf(c) === 1 ? ' kill' : ' kills')) + '</option>').join('');
  }
  const looks = studio_gdLyricLooks(), now = (studio.mkKeep && studio.mkKeep.lyrics && studio.mkKeep.lyrics.look) || 'off';
  studio_show('studio-mk-lyricsrow', looks.length > 0);
  const lb = studio_el('studio-mk-lyrics');
  if (lb) lb.innerHTML = [['off', 'No lyrics']].concat(looks.map(l => [l.key, l.label])).map(o =>
    '<button type="button" class="seg-btn' + (o[0] === now ? ' is-active' : '') + '" data-act="studio-mk-lyrics" data-v="' +
    esc(o[0]) + '" aria-pressed="' + (o[0] === now) + '">' + esc(o[1]) + '</button>').join('');
}

function studio_mkLyrics(v) {
  if (v === 'off') { if (studio.mkKeep) delete studio.mkKeep.lyrics; }
  else studio.mkKeep = Object.assign({}, studio.mkKeep || {}, {lyrics: {look: v}});
  if (studio.mkKeep && !Object.keys(studio.mkKeep).length) studio.mkKeep = null;
  studio_mkFootageDraw();
}

/* BUILD AND DROP WITH ITS DROP OUTSIDE THE PART cannot be made -- the same rule the timeline and the
   server keep (editflow.drop_conflict) -- so Build waits, saying why, with the three ways out. */
function studio_mkDropBlock() {
  const sh = studio.songShape, mk = studio.mk;
  if (studio.style !== 'drop' || !sh || mk.mode !== 'part' || !studio.song) return null;
  const d = studio_mkMainDrop();
  if (d != null && d >= mk.start - 1e-3 && d <= mk.end + 1e-3) return null;
  return d != null
    ? {text: 'Build and drop is built on the drop, and the drop (' + studio_secs(d) + ') is outside the part.',
       fixes: [['move-to-drop', 'Move the part to the drop'], ['mark-drop', 'Mark a drop in this part'], ['other-style', 'Choose another style']]}
    : {text: 'Build and drop is built on the drop, and this song has no drop marked.',
       fixes: [['mark-drop', 'Mark a drop'], ['other-style', 'Choose another style']]};
}

/* THE MAKE PAGE'S BANNER: the kills drawn were planned for a part, drops or a style that have changed
   since. The same words as the timeline's, and the same highlighted way out. */
function studio_mkFlowDraw() {
  const el = studio_el('studio-mk-stale');
  if (!el) return;
  const mk = studio.mk, why = studio_tmStale(studio_tmView('make')), block = studio_mkDropBlock();
  let html = '';
  if (block) {
    html = '<div class="studio-flow is-bad" role="alert"><p class="studio-flow-head">This reel cannot be made with this part</p>' +
      '<p>' + esc(block.text) + '</p><div class="studio-flow-acts">' + block.fixes.map(f =>
        '<button type="button" class="btn btn-sm" data-act="studio-mk-flow" data-do="' + f[0] + '">' + esc(f[1]) + '</button>').join('') + '</div></div>';
  } else if (why.length && mk.planned) {
    const m = mk.planned.made || {};
    const says = {song: 'The song changed', part: 'Song part changed', drops: 'The drops changed', style: 'The style changed'};
    const sub = why[0] === 'part'
      ? 'The kills drawn (dashed) were planned for ' + (m.mode === 'part' ? studio_partRange(m.start, m.end) : 'the part AutoStream chose') +
        '; the part is now ' + (mk.mode === 'part' ? studio_partRange(mk.start, mk.end) : 'AutoStream’s to choose') + '.'
      : 'The kills drawn (dashed) were planned before it.';
    html = '<div class="studio-flow is-stale" role="alert" data-why="' + esc(why.join(' ')) + '"><p class="studio-flow-head">' +
      esc(says[why[0]] + ' — kill timing needs updating') + '</p><p class="studio-small">' + esc(sub) +
      ' Build plans it afresh either way; this only shows where the kills will land.</p><div class="studio-flow-acts">' +
      '<button type="button" class="btn btn-primary btn-sm studio-attn" data-act="studio-mk-flow" data-do="replan">Replan for this section</button>' +
      (why.indexOf('part') >= 0 ? '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-flow" data-do="undo">Undo part change</button>' : '') +
      '</div></div>';
  }
  if (el.getAttribute('data-html') !== html) {
    el.setAttribute('data-html', html);
    el.innerHTML = html;
    el.classList.toggle('hide', !html);
  }
  const btn = studio_el('studio-build-btn');
  if (btn && !studio.mkBuilding) {
    btn.disabled = !!block;
    btn.title = block ? block.text + ' ' + block.fixes.map(f => f[1]).join(', or ') + ' first.' : '';
  }
  studio_mkBadge();
}

function studio_mkFlowAct(b) {
  const what = b.getAttribute('data-do'), mk = studio.mk;
  if (what === 'replan') return studio_mkPlan();
  if (what === 'undo' && mk.planned && mk.planned.made) {
    const was = {start: mk.start, end: mk.end}, m = mk.planned.made;
    mk.mode = m.mode || 'part';
    if (m.mode === 'part') { mk.start = m.start; mk.end = m.end; }
    studio_mkPartChanged(was);
    return;
  }
  if (what === 'move-to-drop') return studio_mkPreset('drop');
  if (what === 'mark-drop') { studio_mkJump('music'); const d = studio_el('studio-mk-dropsbox'); if (d) d.classList.add('is-flash'); return; }
  if (what === 'other-style') return studio_mkJump('style');
}

/* THE MAKE PAGE'S STATE, in the same words as the timeline's badge. */
function studio_mkBadgeState() {
  if (studio.mkBuilding) return {key: 'planning', why: 'Planning the reel.'};
  if (studio.rendering) return {key: 'rendering', why: 'A reel is rendering; build this one when it has finished.'};
  if (studio.mkBusy || studio.mkAsking === 'asking') return {key: 'planning', why: 'Working out what these choices make.'};
  if (studio_mkDropBlock()) return {key: 'failed', why: 'The drop this style is built on is outside the part.'};
  if (studio.mk.planned && studio_tmStale(studio_tmView('make')).length) return {key: 'stale', why: 'The kills drawn were planned before the last change.'};
  if (studio.mkAsking === 'waiting' || !studio.mkVerdict) return {key: 'changed', why: 'Changed since it was last checked.'};
  if (studio.mkVerdict.level === 'bad') return {key: 'failed', why: studio.mkVerdict.text};
  return {key: 'ready', why: studio.mkVerdict.text};
}

function studio_mkBadge() {
  const el = studio_el('studio-mk-badge');
  if (!el) return;
  const st = studio_el('studio-make-scrim').classList.contains('hide') ? null : studio_mkBadgeState();
  el.className = 'studio-badge' + (st ? ' is-' + st.key : '');
  el.setAttribute('data-state', st ? st.key : '');
  el.title = st ? st.why : '';
  el.innerHTML = studio_badgeHtml(st);
}

/* BACK TO THE STEPS, from All settings: the guide at the step it was on, with what was chosen here --
   the style, the shape, the clips, the part, the drops, the lyrics -- in it. One draft, two views. */
function studio_mkToGuide() {
  const gd = studio.gd, ret = studio.mkFrom || {};
  if (studio.style) gd.style = studio.style;
  gd.auto = false;
  gd.fmt = studio.fmt; gd.fit = studio.vfit;
  const build = studio.style === 'drop' && studio.buildClip
    ? Object.keys(studio.clipIndex).find(id => studio.clipIndex[id].path === studio.buildClip) || '' : '';
  gd.setup = build;
  gd.quick = studio.selected.filter(id => id !== build);
  gd.lyrics = (studio.mkKeep && studio.mkKeep.lyrics && studio.mkKeep.lyrics.look) || 'off';
  gd.name = studio_el('studio-name').value || gd.name;
  gd.step = ret.step == null ? 4 : ret.step;
  gd.verdict = null;
  studio.mkFrom = null;
  studio_show('studio-make-scrim', false);
  studio_show('studio-guide-scrim', true);
  studio_makePage(true);
  studio_gdAudioWire();
  studio_gdDraw();
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
  ['style', 'music', 'footage', 'timing', 'look'].forEach(sec => {
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

/* Play the cards on screen, pause the rest: eight loops decoding off screen is waste. */
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
    const p = studio_partFor(sh, studio.fmt, studio.style === 'drop' ? studio_mkMainDrop() : null);
    mk.start = p[0]; mk.end = p[1];
  }
  studio_el('studio-mk-drop').disabled = studio_mkMainDrop() == null;
  studio_mkDraw();
}

/* THE PART A PAGE DRAWS BY ITSELF, from the song, the shape and -- for Build and drop -- the drop.
   One function for the Make page and the guided maker, so the part the guide judged is the part
   the Make page shows when the guide hands over: the guide used to read the Make page's shape
   (16:9 until it was changed) and judged a 46 s part for a 30 s vertical reel. */
function studio_partFor(sh, fmt, drop) {
  const bar = 4 * (sh.beat || 60 / sh.bpm);
  const want = fmt === 'vertical' ? 30 : 46;
  const bars = Math.max(1, Math.round(want / bar));
  let from = sh.drums_in || (sh.beats && sh.beats[0]) || 0;
  /* BUILD AND DROP NEEDS ITS DROP INSIDE THE PART, with the build before it. From where the
     drums come in, Lalala's 30 s part left 2 s before its first drop: the take could not fit,
     so it went to the second drop 18 s in, and the reel was the 15 s that were left. */
  if (drop != null) from = Math.max(0, drop - Math.min(16, want / 2));
  const start = studio_nearestBeat(sh, Math.max(0, Math.min(from, sh.seconds - bar)));
  return [start, Math.min(sh.seconds, start + bars * bar)];
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

/* ===== THE SONG'S TIMING: ONE DRAFT, ONE EDITOR ===================================================== */

/* ONE EDITOR FOR THE PART, THE KILL MARKS AND THE DROPS, wherever they are edited. They used to be
   three: the guide's drop view, the Make page's "Part of the song" and Kills, and the timeline's Song
   tab each kept its own copy and behaved its own way -- on the Song tab, dragging the part carried
   every mark along with it, a fixed distance from the part's start, off the beats it had been on, and
   nothing said the timing no longer held (Hardik's recording: 0:00-0:44 dragged to 0:59-2:07, 21
   diamonds still where they were relative to the start, covering 40% of the new part).

   Now there is one machinery -- these functions -- over a DRAFT with one shape, and two drafts:

     studio.mk   the reel being MADE: the guide and the Make page edit it, and "All settings" is the
                 same draft seen fuller, so nothing is copied between them
     studio.sg   the reel OPEN ON THE TIMELINE, read from its project every time it is drawn
                 (studio_sgSync) and written back to it as one undoable edit (studio_sgCommit)

   A draft is {start, end, touched, mode, hand, edited, planned, drops, sel, nid}: the part in song
   seconds; the kills as the player has them (`hand`, a list of {id, t, auto}, once `edited`) or where
   the plan put them (`planned`); the drops, null while they are the song's own. A mark the player
   placed or moved is theirs (auto false) and is never moved for them. AutoStream's marks are placed
   again whenever the reel is planned or re-timed.

   STALE is the plan no longer matching the draft: the part moved, the song changed, the drops moved.
   It is never resolved behind the player's back -- see studio_flow, below. */

/* THE DROPS, AS MARKS. The main bass drops the song analysis found used to be one thin line, and only
   the biggest of them; they are now marks on the song like the kills, every one found, and the player
   can move them, add their own and take AutoStream's away. A draft's `drops` is null while they are
   AutoStream's -- and only then is nothing sent, so the planner keeps reading the song itself. These
   read, own, choose from and send any draft's list the same way. */
function studio_dropsOf(drops, sh) {
  if (drops) return drops.map(d => ({id: d.id, t: d.t, hand: !d.auto}));
  if (!sh) return [];
  const found = (sh.drops && sh.drops.length) ? sh.drops : (sh.drop ? [sh.drop] : []);
  return found.map((t, i) => ({id: 'a' + i, t: t, hand: false}));
}
/* the list as the player's to change: the analysis's drops copied in, marked as AutoStream's */
function studio_dropsOwned(drops, sh) {
  return drops || studio_dropsOf(null, sh).map(d => ({id: d.id, t: d.t, auto: true}));
}
/* THE drop: the analysis's own, or -- once the player has marked theirs -- the one of theirs nearest it,
   the same choice the server makes with the list. */
function studio_dropsMain(drops, sh) {
  if (!drops) return sh && sh.drop ? sh.drop : null;
  if (!drops.length) return null;
  const ref = sh && sh.drop;
  return ref ? drops.reduce((b, d) => Math.abs(d.t - ref) < Math.abs(b - ref) ? d.t : b, drops[0].t) : drops[0].t;
}
function studio_dropsSent(drops) { return drops.map(d => Math.round(d.t * 1000) / 1000); }
/* a drop the player placed: snapped to that song's beat if that page's box says so */
function studio_dropNew(t, snapBox, sh) {
  studio.mk.nid = (studio.mk.nid || 0) + 1;
  const box = studio_el(snapBox || 'studio-mk-snap');
  const at = box && box.checked ? studio_nearestBeat(sh || studio.songShape, t) : Math.round(t * 1000) / 1000;
  return {id: 'u' + studio.mk.nid, t: at, auto: false};
}

/* The two places the full editor is mounted, each with its own canvas, player and snap box. */
function studio_tmView(where) {
  if (where === 'song') {
    const sg = studio.sg;
    const pad = Math.max(0.5, (sg.end - sg.start) * 0.04), sh = sg.shape;
    return {where: 'song', T: sg, sh: sh, cv: 'studio-sg-detail', snap: 'studio-sg-snap', audio: 'studio-sg-audio',
            song: sg.song, part: {start: sg.start, end: sg.end},
            span: {start: Math.max(0, sg.start - pad), end: Math.min(sh ? sh.seconds : sg.end + pad, sg.end + pad)}};
  }
  const sp = studio_mkKillSpan();
  return {where: 'make', T: studio.mk, sh: studio.songShape, cv: 'studio-mk-kills', snap: 'studio-mk-snap',
          audio: 'studio-mk-audio', song: studio.song, part: sp, span: sp};
}

/* EVERY MARK IS AN OBJECT WITH AN ID: {id, t, auto, name}. `auto` is "AutoStream put it there", so
   the page can draw AutoStream's kills and the player's in different colours once both are on the
   song -- they used to become one colour the moment one was touched, and nobody could tell which of
   fifty they had placed. The id is what a selection holds, so selecting survives a sort. */

/* The kills as they stand: the player's own once they have touched one, else where the plan put them.
   A plan's mark that is one of the player's own (an anchor kept from before) is drawn as theirs. */
function studio_tmKillList(T) {
  if (T.edited) return T.hand.map(k => ({id: k.id, t: k.t, hand: !k.auto, name: k.name || ''}));
  if (T.planned) return T.planned.marks.map((t, i) => ({id: 'p' + i, t: t, hand: !!(T.planned.hand && T.planned.hand[i]),
                                                        name: T.planned.names[i] || ''}));
  return [];
}

/* A first touch makes the plan the player's: every kill becomes a mark they can move, so moving one does
   not discard the rest. The ones they did not touch stay AutoStream's, and are drawn as such. */
function studio_tmOwn(T) {
  if (T.edited) return;
  T.hand = T.planned ? T.planned.marks.map((t, i) => ({id: 'p' + i, t: t, auto: !(T.planned.hand && T.planned.hand[i]),
                                                       name: T.planned.names[i] || ''})) : [];
  T.edited = true;
}

function studio_tmDropList(v) { return studio_dropsOf(v.T.drops, v.sh); }
function studio_tmOwnDrops(v) { if (!v.T.drops) v.T.drops = studio_dropsOwned(null, v.sh); }
function studio_tmMainDrop(v) { return studio_dropsMain(v.T.drops, v.sh); }

/* EXACT, UNLESS ASKED. A mark is where the player pressed K or let go of it, to the millisecond: it used
   to be pulled to the nearest beat, so a kill marked on an off-beat hit landed somewhere they had not
   put it. Snapping is a choice on the page, off until it is ticked. */
function studio_tmSnap(v, t) {
  const box = studio_el(v.snap);
  return box && box.checked ? studio_nearestBeat(v.sh, t) : Math.round(t * 1000) / 1000;
}

/* Which kind an id is: kills are p# (planned) or h# (placed), drops a# (found) or u# (placed). */
function studio_mkIsDrop(id) { return /^[au]/.test(String(id)); }

/* After every change to a draft: the Make page redraws (and asks its chip again for a drop); the Song
   tab writes the change to the reel, as one step of undo. */
function studio_tmChanged(v, label, drop) {
  if (v.where === 'song') { studio_sgCommit(label); return; }
  if (drop) studio_mkDropsChanged(); else studio_mkKillsDraw();
}

function studio_tmAddMark(v, t) {
  if (!v.sh) { toast('Choose a song first.', 'warn'); return false; }
  if (t < v.part.start - 0.01 || t > v.part.end + 0.01) { toast('Marks go inside the part you are using.', 'warn'); return false; }
  const T = v.T;
  studio_tmOwn(T);
  const at = studio_tmSnap(v, t);
  const near = T.hand.find(k => Math.abs(k.t - at) < 0.03);
  /* A MARK ON ONE OF AUTOSTREAM'S IS THE PLAYER CLAIMING IT: it becomes theirs, at their time, and is
     never moved for them again. It used to be dropped without a word, so K pressed on a kill the plan
     had already marked did nothing at all. */
  if (near && !near.auto) return false;
  if (near) {
    near.auto = false; near.t = at;
    studio_tmChanged(v, 'A kill marked at ' + studio_secs(at));
    return true;
  }
  T.nid = (T.nid || 0) + 1;
  T.hand.push({id: 'h' + T.nid, t: at, auto: false, name: ''});
  T.hand.sort((x, y) => x.t - y.t);
  studio_tmChanged(v, 'A kill marked at ' + studio_secs(at));
  return true;
}

/* A DROP MARKED BY THE PLAYER: where the bass comes in, as they hear it. Build and drop builds into
   it, and the drop flash goes on the kill that lands on it. */
function studio_tmAddDrop(v, t) {
  if (!v.sh) { toast('Choose a song first.', 'warn'); return; }
  if (t < v.part.start - 0.01 || t > v.part.end + 0.01) { toast('That is outside the part you chose.', 'warn'); return; }
  studio_tmOwnDrops(v);
  v.T.drops.push(studio_dropNew(t, v.snap, v.sh));
  v.T.drops.sort((x, y) => x.t - y.t);
  studio_tmChanged(v, 'A drop marked at ' + studio_secs(t), true);
}

/* Remove marks by id, kills and drops alike -- one, or everything selected. */
function studio_tmDelIds(v, ids) {
  const T = v.T, kill = ids.filter(id => !studio_mkIsDrop(id)), drop = ids.filter(studio_mkIsDrop);
  if (kill.length) {
    studio_tmOwn(T);
    T.hand = T.hand.filter(k => kill.indexOf(k.id) < 0);
  }
  if (drop.length) {
    studio_tmOwnDrops(v);
    T.drops = T.drops.filter(d => drop.indexOf(d.id) < 0);
  }
  T.sel = T.sel || {};
  ids.forEach(id => { delete T.sel[id]; });
  studio_tmChanged(v, ids.length === 1 ? (drop.length ? 'A drop removed' : 'A kill mark removed')
                                        : ids.length + ' marks removed', drop.length > 0);
}

function studio_tmNudgeMark(v, id, by) {
  const T = v.T, drop = studio_mkIsDrop(id);
  if (drop) studio_tmOwnDrops(v); else studio_tmOwn(T);
  const m = (drop ? T.drops : T.hand).find(x => x.id === id);
  if (!m) return;
  m.t = Math.max(0, Math.round((m.t + by) * 1000) / 1000);
  m.auto = false;
  (drop ? T.drops : T.hand).sort((x, y) => x.t - y.t);
  studio_tmChanged(v, drop ? 'A drop moved' : 'A kill mark moved', drop);
}

/* Move every selected mark by the same amount. One that is moved is the player's from then on. */
function studio_tmMoveSel(v, ids, dt) {
  const T = v.T, span = v.span;
  const list = Object.keys(ids), kills = list.some(id => !studio_mkIsDrop(id)), drops = list.some(studio_mkIsDrop);
  const one = list.length === 1;
  const move = m => {
    if (!ids[m.id]) return;
    const to = Math.max(span.start, Math.min(span.end, m.t + dt));
    m.t = one ? studio_tmSnap(v, to) : Math.round(to * 1000) / 1000;
    m.auto = false;
  };
  if (kills) { studio_tmOwn(T); T.hand.forEach(move); T.hand.sort((x, y) => x.t - y.t); }
  if (drops) { studio_tmOwnDrops(v); T.drops.forEach(move); T.drops.sort((x, y) => x.t - y.t); }
  studio_tmChanged(v, drops && !kills ? 'A drop moved' : list.length > 1 ? list.length + ' marks moved' : 'A kill mark moved', drops);
}

function studio_tmClearMarks(v) {
  const T = v.T;
  T.hand = []; T.edited = false;
  Object.keys(T.sel || {}).forEach(id => { if (!studio_mkIsDrop(id)) delete T.sel[id]; });
  studio_tmChanged(v, 'Kill marks back to AutoStream’s');
}

function studio_tmClearDrops(v) {
  const T = v.T;
  T.drops = null;
  Object.keys(T.sel || {}).forEach(id => { if (studio_mkIsDrop(id)) delete T.sel[id]; });
  studio_tmChanged(v, 'Drops back to AutoStream’s', true);
}

/* WHAT THE PLAN HAS NOT CAUGHT UP WITH, as reasons: 'song', 'part', 'marks', 'drops', 'style'. The reel's
   are its project's draft (clips/editflow.py, the same names); the Make page's are what changed since
   "Show where the kills will land" planned the marks drawn. [] when the timing holds. */
function studio_tmStale(v) {
  if (v.where === 'song') {
    const d = (studio.project && studio.project.draft) || {};
    return ['song', 'part', 'marks', 'drops'].filter(k => k === 'part' ? (d.start !== undefined || d.end !== undefined) : d[k] !== undefined);
  }
  const T = v.T, m = T.planned && T.planned.made;
  if (!m) return [];
  const out = [];
  if ((m.song || '') !== (studio.song || '')) out.push('song');
  else if (m.mode !== T.mode || (T.mode === 'part' && (Math.abs(m.start - T.start) > 5e-4 || Math.abs(m.end - T.end) > 5e-4))) out.push('part');
  if (m.drops !== JSON.stringify(T.drops ? studio_dropsSent(T.drops) : null)) out.push('drops');
  if (m.style !== studio.style) out.push('style');
  return out;
}

/* THE MARKS, DRAWN THE SAME WAY EVERYWHERE: AutoStream's hollow, the player's solid, a selected one
   ringed -- and, while the timing is stale, AutoStream's dashed and faint, at the song seconds they
   were planned on, because that is where they still are and they are about to be placed again. */
function studio_tmDiamond(ctx, x, y, k, o) {
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x, y - 8); ctx.lineTo(x + 8, y); ctx.lineTo(x, y + 8); ctx.lineTo(x - 8, y); ctx.closePath();
  if (o.ghost && !k.hand) {
    ctx.globalAlpha = 0.5; ctx.setLineDash([3, 3]);
    ctx.fillStyle = o.surface; ctx.fill(); ctx.strokeStyle = o.auto; ctx.lineWidth = 1.5; ctx.stroke();
  } else if (k.hand) { ctx.fillStyle = o.accent; ctx.fill(); }
  else { ctx.fillStyle = o.surface; ctx.fill(); ctx.strokeStyle = o.auto; ctx.lineWidth = 1.75; ctx.stroke(); }
  ctx.restore();
}

/* Where the lanes sit on the canvas: drops along the top, kills through the middle. */
const MK_DROP_LANE = 26;
const MK_KILLS_H = 140;

/* THE PART UP CLOSE: the song's loudness, the part's beats and hits, the drops on their lane and the
   kills on theirs, the playhead. One drawing for the Make page and the Song tab; each mounts it on its
   own canvas. Drawn a little wider than the part on the Song tab, so the part's edges show. */
function studio_tmKillsDraw(v) {
  const sh = v.sh, T = v.T;
  if (!sh) return;
  T.sel = T.sel || {};
  const list = studio_tmKillList(T), drops = studio_tmDropList(v);
  const c = studio_sgCanvas(v.cv, MK_KILLS_H);
  if (!c || !sh.peaks) return {list: list, drops: drops};
  const {ctx, W, H} = c, span = v.span, len = Math.max(0.5, span.end - span.start);
  const X = t => (t - span.start) / len * W, top = MK_DROP_LANE, mid = top + (H - top - 14) / 2;
  const css = getComputedStyle(document.documentElement);
  const tok = (n, d) => css.getPropertyValue(n).trim() || d;
  const accent = tok('--accent', '#5aa9ff'), auto = tok('--ok', '#4fc97a'), warn = tok('--warn', '#e3b341');
  const faint = tok('--text-tertiary', '#8a8a8a'), text = tok('--text-primary', '#fff'), surface = tok('--surface', '#111');
  const n = sh.peaks.length;
  /* outside the part, dimmed: the part is what is cut to */
  ctx.fillStyle = faint;
  for (let x = 0; x < W; x++) {
    const t = span.start + x / W * len;
    const amp = (sh.peaks[Math.min(n - 1, Math.max(0, Math.floor(t / sh.seconds * n)))] || 0) * (mid - top - 4);
    ctx.globalAlpha = (t >= v.part.start && t <= v.part.end) ? 0.45 : 0.15;
    ctx.fillRect(x, mid - amp, 1, amp * 2 || 1);
  }
  ctx.globalAlpha = 1;
  /* THE PART'S OWN BEATS. They are read from the song where the part is, so a part dragged elsewhere
     shows the grid its kills will be placed on, not the one they were. */
  studio_beatGrid(ctx, X, H - 14, sh, {width: W, alpha: 0.9, top: top, height: H - 14 - top});
  ctx.fillStyle = faint;
  ctx.globalAlpha = 0.7;
  (sh.hits || []).forEach(t => { if (t >= span.start && t <= span.end) ctx.fillRect(X(t) - 0.5, H - 12, 1, 8); });
  ctx.globalAlpha = 1;
  if (v.where === 'song') {
    ctx.fillStyle = accent;
    ctx.fillRect(X(v.part.start) - 1, 0, 3, H); ctx.fillRect(X(v.part.end) - 1, 0, 3, H);
  }
  ctx.fillStyle = tok('--surface-sunken', '#080b10');
  ctx.fillRect(0, 0, W, top - 2);
  const md = T.markDrag, dt = md && md.moved ? md.dt : 0;
  const at = (id, t) => (md && md.moved && md.ids[id]) ? t + dt : t;
  drops.forEach(d => {
    const t = at(d.id, d.t);
    if (t < span.start - 0.01 || t > span.end + 0.01) return;
    const x = X(t), on = !!T.sel[d.id];
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
  const why = studio_tmStale(v), ghost = why.indexOf('part') >= 0 || why.indexOf('style') >= 0;
  /* A new song's marks were beats of another song: not drawn on this one at all. */
  const shown = why.indexOf('song') >= 0 ? list.filter(k => k.hand) : list;
  shown.forEach((k, i) => {
    const t = at(k.id, k.t);
    if (t < span.start - 0.01 || t > span.end + 0.01) return;
    const x = X(t), on = !!T.sel[k.id];
    studio_tmDiamond(ctx, x, mid, k, {ghost: ghost, accent: accent, auto: auto, surface: surface});
    if (on) {
      ctx.beginPath(); ctx.arc(x, mid, 12, 0, Math.PI * 2);
      ctx.strokeStyle = text; ctx.lineWidth = 2; ctx.stroke();
    }
    ctx.fillStyle = k.hand ? accent : auto;
    ctx.globalAlpha = ghost && !k.hand ? 0.5 : 1;
    ctx.font = '10px monospace';
    ctx.fillText(String(i + 1), x - 3, mid - 13);
    ctx.globalAlpha = 1;
  });
  const bs = T.boxSel;
  if (bs) {
    ctx.fillStyle = accent; ctx.globalAlpha = 0.15;
    ctx.fillRect(Math.min(X(bs.t0), X(bs.t1)), 0, Math.abs(X(bs.t1) - X(bs.t0)), H);
    ctx.globalAlpha = 1;
  }
  const a = studio_el(v.audio);
  if (a && a.getAttribute('data-song') === v.song && (!a.paused || a.currentTime > 0)) {
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(a.currentTime) - 1, 0, 2, H);
  }
  c.cv.setAttribute('data-t0', span.start); c.cv.setAttribute('data-t1', span.end);
  return {list: list, drops: drops};
}

/* THE CANVAS. Click a mark to select it (Ctrl or Shift adds to the selection), drag to move it -- and
   everything selected with it -- Shift-drag the empty song to box-select, click the empty song to hear
   it from there, double-click to add or remove. The top lane is the drops, the rest the kills. */
function studio_tmKillPointer(v, e, seek) {
  const cv = studio_el(v.cv), T = v.T;
  if (!cv || !v.sh) return;
  T.sel = T.sel || {};
  const redraw = () => { if (v.where === 'song') studio_sgDraw(); else studio_mkKillsDraw(); };
  const r = cv.getBoundingClientRect(), span = v.span, len = span.end - span.start;
  const x = Math.max(0, Math.min(r.width, e.clientX - r.left)), y = e.clientY - r.top;
  const t = span.start + x / r.width * len;
  const inDrops = y < MK_DROP_LANE * r.height / MK_KILLS_H;
  const pool = inDrops ? studio_tmDropList(v) : studio_tmKillList(T);
  let near = -1, gap = 11;
  pool.forEach((k, i) => { const d = Math.abs((k.t - span.start) / len * r.width - x); if (d < gap) { gap = d; near = i; } });
  const hit = near >= 0 ? pool[near] : null;
  const inPart = u => Math.max(v.part.start, Math.min(v.part.end, u));
  if (e.type === 'pointerdown') {
    if (e.button !== undefined && e.button !== 0) return;
    if (hit) {
      if (e.ctrlKey || e.metaKey || e.shiftKey) {
        if (T.sel[hit.id]) delete T.sel[hit.id]; else T.sel[hit.id] = true;
        redraw();
      } else {
        if (!T.sel[hit.id]) T.sel = {[hit.id]: true};
        const ids = {};
        Object.keys(T.sel).forEach(id => { ids[id] = true; });
        T.markDrag = {t0: t, dt: 0, ids: ids, moved: false};
        try { cv.setPointerCapture(e.pointerId); } catch (err) { /* a mouse still works */ }
        redraw();
      }
    } else if (e.shiftKey) {
      T.boxSel = {t0: t, t1: t, add: e.ctrlKey || e.metaKey};
      try { cv.setPointerCapture(e.pointerId); } catch (err) { /* a mouse still works */ }
    } else {
      T.sel = {};
      seek(Math.max(span.start, Math.min(span.end, t)));      /* click the song: hear it from there */
    }
    e.preventDefault();
  } else if (e.type === 'pointermove' && T.markDrag) {
    const md = T.markDrag;
    md.dt = t - md.t0;
    md.moved = md.moved || Math.abs(md.dt) * r.width / len > 2;
    redraw();
  } else if (e.type === 'pointermove' && T.boxSel) {
    T.boxSel.t1 = t;
    redraw();
  } else if ((e.type === 'pointerup' || e.type === 'pointercancel') && T.markDrag) {
    const md = T.markDrag;
    T.markDrag = null;
    if (md.moved && e.type === 'pointerup') studio_tmMoveSel(v, md.ids, md.dt);
    else redraw();
  } else if ((e.type === 'pointerup' || e.type === 'pointercancel') && T.boxSel) {
    const bs = T.boxSel, lo = Math.min(bs.t0, bs.t1), hi = Math.max(bs.t0, bs.t1);
    T.boxSel = null;
    if (!bs.add) T.sel = {};
    studio_tmKillList(T).concat(studio_tmDropList(v)).forEach(k => { if (k.t >= lo && k.t <= hi) T.sel[k.id] = true; });
    redraw();
  } else if (e.type === 'dblclick') {
    if (hit) studio_tmDelIds(v, [hit.id]);
    else if (inDrops) studio_tmAddDrop(v, inPart(t));
    else studio_tmAddMark(v, inPart(t));
  }
}

/* THE WHOLE SONG, WITH THE PART ON IT: drag the part to move it, an edge to resize it, click elsewhere
   to move it there. One gesture for the Make page and the Song tab.

   WHILE IT IS DRAGGED, ONLY THE RANGE AND THE WAVEFORM MOVE. Nothing is planned, no shot is touched and
   no mark moves -- a mark is a moment of the song and stays at its second. On release the part lands
   on a beat, and only if it really changed (its start or its end, even at the same length) is that a
   change at all: `commit` is called with what it was, so a surface can tell. `T.drag` is the live
   range, which is what the canvases draw while it exists. */
function studio_tmPartPointer(e, o) {
  const T = o.T, sh = o.sh, cv = o.cv;
  if (!sh || !cv) return;
  if (e.type === 'pointerdown' && o.seekOnly) {
    const r = cv.getBoundingClientRect();
    o.seek((e.clientX - r.left) / r.width * sh.seconds);
    return;
  }
  if (e.type === 'pointerdown') {
    const r = cv.getBoundingClientRect();
    const t = (e.clientX - r.left) / r.width * sh.seconds;
    const edge = 6 / r.width * sh.seconds;
    const kind = Math.abs(t - T.start) < edge ? 'start' : Math.abs(t - T.end) < edge ? 'end'
      : (t > T.start && t < T.end) ? 'move' : 'jump';
    const was = {start: T.start, end: T.end};
    if (kind === 'jump') {
      const len = T.end - T.start;
      T.start = studio_nearestBeat(sh, Math.max(0, Math.min(sh.seconds - len, t - len / 2)));
      T.end = Math.min(sh.seconds, T.start + len);
      o.commit(was);
      return;
    }
    T.drag = {kind: kind, x0: e.clientX, start: T.start, end: T.end, w: r.width, pointer: e.pointerId, was: was};
    try { cv.setPointerCapture(e.pointerId); } catch (err) { /* fine without */ }
    e.preventDefault();
    return;
  }
  const g = T.drag;
  if (!g || e.pointerId !== g.pointer) return;
  const dt = (e.clientX - g.x0) / g.w * sh.seconds;
  if (e.type === 'pointermove') {
    if (g.kind === 'start') T.start = Math.max(0, Math.min(T.end - 1, g.start + dt));
    else if (g.kind === 'end') T.end = Math.max(T.start + 1, Math.min(sh.seconds, g.end + dt));
    else {
      const len = g.end - g.start;
      T.start = Math.max(0, Math.min(sh.seconds - len, g.start + dt));
      T.end = T.start + len;
    }
    o.redraw();
    return;
  }
  T.drag = null;
  if (e.type === 'pointercancel') { T.start = g.was.start; T.end = g.was.end; o.redraw(); return; }
  /* Dropped on a beat, so the reel's cuts are the song's beats. */
  const len = T.end - T.start, bar = 4 * (sh.beat || 60 / sh.bpm);
  if (g.kind !== 'end') {
    T.start = studio_nearestBeat(sh, T.start);
    if (g.kind === 'move') T.end = Math.min(sh.seconds, T.start + len);
    else T.start = Math.min(T.end - bar / 8, T.start);
  } else {
    T.end = Math.max(T.start + bar / 4, studio_nearestBeat(sh, T.end));
  }
  o.commit(g.was);
}

/* ----- the Make page's mounting of it ----- */

function studio_mkKillList() { return studio_tmKillList(studio.mk); }
function studio_mkOwn() { studio_tmOwn(studio.mk); }
function studio_mkDropList() { return studio_dropsOf(studio.mk.drops, studio.songShape); }
function studio_mkOwnDrops() { studio_tmOwnDrops(studio_tmView('make')); }
function studio_mkMainDrop() { return studio_dropsMain(studio.mk.drops, studio.songShape); }

function studio_mkKillSpan() {
  const sh = studio.songShape;
  if (!sh) return {start: 0, end: 1};
  const sp = studio_mkSpan();
  return {start: sp.start, end: Math.max(sp.end, sp.start + 1)};
}

function studio_mkSnap(t, boxId) {
  const box = studio_el(boxId || 'studio-mk-snap');
  return box && box.checked ? studio_nearestBeat(studio.songShape, t) : Math.round(t * 1000) / 1000;
}

function studio_mkSelCount() {
  return Object.keys(studio.mk.sel || {}).length;
}

function studio_mkKillsDraw() {
  const box = studio_el('studio-mk-killsbox');
  if (!box) return;
  const sh = studio.songShape, mk = studio.mk;
  box.classList.toggle('hide', !sh);
  studio_show('studio-mk-dropsbox', !!sh);
  const note = studio_el('studio-mk-killnote');
  if (!sh) {
    if (note) note.textContent = '';
    return;
  }
  const v = studio_tmView('make');
  const list = studio_tmKillList(mk), drops = studio_tmDropList(v);
  const mine = list.filter(k => k.hand).length;
  if (note) {
    note.textContent = mk.edited
      ? list.length + ' kill(s): ' + mine + ' placed by you, ' + (list.length - mine) + ' by AutoStream. Build puts every shot around them; "Back to automatic" lets AutoStream choose again.'
      : mk.planned
        ? 'Where the plan puts ' + list.length + ' kills on the song. Drag one, press K at the playhead, or double-click the song to place your own.'
        : 'AutoStream puts each kill on a hit of the song. Press "Show where the kills will land" to see them here, then move any you like.';
  }
  studio_tmKillsDraw(v);
  studio_mkListDraw(list, drops);
  studio_flowDraw();
}

/* The lists under the song: what lands where, whose each one is, and a box to pick several.
   Rebuilt only when something in them changed -- the playhead redraws the canvas sixty times a
   second, and a list rebuilt that often eats the click that was meant for one of its boxes. */
function studio_mkListDraw(list, drops) {
  const mk = studio.mk;
  mk.sel = mk.sel || {};
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

/* Where the playhead is, or the start of the part before anything has played. */
function studio_mkHead() {
  const a = studio_el('studio-mk-audio');
  return a && a.getAttribute('data-song') === studio.song && a.readyState >= 1 ? a.currentTime : studio_mkSpan().start;
}

function studio_mkAddMark(at) { studio_tmAddMark(studio_tmView('make'), at !== undefined ? at : studio_mkHead()); }
function studio_mkAddDrop(at) { studio_tmAddDrop(studio_tmView('make'), at !== undefined ? at : studio_mkHead()); }

/* A change to the drops: the chip is asked again, and the marks drawn were planned around the old ones. */
function studio_mkDropsChanged() {
  studio_mkChip();
  studio_mkDraw();
}

function studio_mkDelIds(ids) { studio_tmDelIds(studio_tmView('make'), ids); }
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

function studio_mkNudgeMark(id, d) { studio_tmNudgeMark(studio_tmView('make'), id, d * 0.1); }
function studio_mkClearMarks() { studio_tmClearMarks(studio_tmView('make')); }
function studio_mkClearDrops() { studio_tmClearDrops(studio_tmView('make')); }

/* A style, a part, a song or the clips changed. The marks a plan PLACED were planned on what was there
   before, so they no longer hold -- but they are not wiped: they stay where they were, dashed, and the
   page says so and offers to plan again (studio_flowDraw). Marks the player placed are theirs and stay
   as they are; they are about the song, not the plan. */
function studio_mkStale() {
  studio_mkChip();
  studio_mkKillsDraw();
}

async function studio_mkPlan() {
  if (!studio.selected.length || !studio.song) { toast('Choose a song first: kills land on its hits.', 'warn'); return; }
  const btn = studio_el('studio-mk-plan'), msg = studio_el('studio-mk-killmsg'), mk = studio.mk;
  btn.disabled = true;
  msg.textContent = 'Planning the reel to find where each kill lands... this is the plan Build would make' +
    (studio.arrange === 'fit' ? ', and a perfect fit takes up to ~30 s.' : '.');
  /* What this plan is made on, so the page can tell when the part or the drops have moved past it --
     and so an answer to an older question is dropped rather than drawn over a newer part. */
  const body = studio_planBody(false);
  const made = {song: studio.song, mode: mk.mode, start: mk.start, end: mk.end, style: studio.style,
                drops: JSON.stringify(mk.drops ? studio_dropsSent(mk.drops) : null)};
  const ask = mk.planAsk = (mk.planAsk || 0) + 1;
  studio.mkBusy = true;
  studio_mkBadge();
  try {
    const r = await API.post('/api/studio/plan', body);
    if (ask !== mk.planAsk) return;
    if (!r || !r.ok) { msg.textContent = (r && r.error) || 'Could not plan that reel.'; return; }
    const p = r.project, marks = (p.song_marks || []).slice();
    const names = (p.shots || []).map(x => (x.caption || x.name || '').replace(/\.mp4$/i, ''));
    mk.planned = {marks: marks, names: names, made: made};
    msg.textContent = marks.length + ' kills placed on the song.';
  } finally {
    if (ask === mk.planAsk) { btn.disabled = false; studio.mkBusy = false; }
    studio_mkKillsDraw();
    studio_mkBadge();
  }
}

function studio_mkKillPointer(e) { studio_tmKillPointer(studio_tmView('make'), e, studio_mkSeek); }

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
  const bar = studio_mkBar(), step = how === 'bar' ? bar : -bar, was = {start: mk.start, end: mk.end};
  if (what === 'start') {
    const len = mk.end - mk.start;
    mk.start = Math.max(0, Math.min(sh.seconds - bar, mk.start + step));
    mk.end = Math.min(sh.seconds, mk.start + len);
  } else {
    mk.end = Math.max(mk.start + bar, Math.min(sh.seconds, mk.end + step));
  }
  studio_mkPartChanged(was);
}

function studio_mkPreset(which) {
  const sh = studio.songShape, mk = studio.mk;
  if (!sh) return;
  const bar = studio_mkBar(), len = mk.end - mk.start, was = {start: mk.start, end: mk.end};
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
  studio_mkPartChanged(was);
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
  yt.target = target === 'song' || target === 'guide' ? target : 'make';
  /* The Mac keeps footage in ~/Movies (macos/paths.py), not Videos. */
  if (window.BOOT && BOOT.platform === 'macos') studio_el('studio-yt-folder').textContent = '~/Movies/AutoStream/songs';
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
  /* From the guide: the songs list it shows is read again (the new file is in it now), and the
     song is chosen there, on its Song step, with the drops on it -- the guide stays open. */
  if (yt.target === 'guide') {
    const r = await API.get('/api/studio/songs').catch(() => null);
    if (r && r.ok) studio.songList = r.songs || [];
    studio.gd.step = 1;
  }
  const ok = yt.target === 'song' ? await studio_sgUseSong(f.path)
    : yt.target === 'guide' ? await studio_gdUseSong(f.path, f.title || '')
    : await studio_useSong(f.path, f.title || '');
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
  const mk = studio.mk;
  studio_tmPartPointer(e, {T: mk, sh: studio.songShape, cv: studio_el('studio-mk-wave'),
    /* Nothing to drag while AutoStream chooses; a click is a seek. */
    seekOnly: mk.mode !== 'part', seek: studio_mkSeek, redraw: studio_mkDraw,
    commit: was => studio_mkPartChanged(was)});
}

/* THE PART, MOVED ON THE MAKE PAGE -- by a drag, a nudge or a preset. Only a real change counts, and
   makes the part the player's (`touched`). The marks drawn stay where they are; studio_tmStale says
   they no longer hold, and "Undo part change" puts back the part they were planned on. */
function studio_mkPartChanged(was) {
  const mk = studio.mk;
  if (Math.abs(was.start - mk.start) < 5e-4 && Math.abs(was.end - mk.end) < 5e-4) { studio_mkDraw(); return; }
  mk.touched = true;
  studio_mkStale();
  studio_mkDraw();
}

/* =======================================================================
   THE PARTS BIN
   A reel is one pick from each drawer. Each pick is shown by a two-second
   example cut from this machine's own clips (clips/examples.py), so a choice
   is made by watching rather than by reading "k02 Shake" in a list. The
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
  /* The player's own marks on a reel being rebuilt, as constraints rather than the whole list. */
  if (studio.song && !body.marks && studio.mkAnchors && studio.mkAnchors.length) body.anchors = studio.mkAnchors.slice();
  /* THE DROPS, once the player has touched them -- every plan, the preview's as well as Build's, so
     the kills it shows are the ones it will build around them. An empty list is "no drop at all". */
  if (studio.song && studio.mk.drops) body.drops = studio_dropsSent(studio.mk.drops);
  /* What the guided maker handed over that belongs to the reel, not the plan: the lyrics' look.
     The page has no control of its own for it, so it is said in the facts line while it rides. */
  if (studio.mkKeep) body.keep = JSON.parse(JSON.stringify(studio.mkKeep));
  return body;
}

async function studio_build(opts) {
  /* The guided maker plans from its own page: its button, its chip for the words, and its own
     request (`body`, from studio_gdBody) -- a new reel, never the rebuild the Make page may hold. */
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
  studio.mkBuilding = true;
  studio_mkBadge();
  const ad = o.body ? null : studio.adding;
  const body = o.body || studio_planBody(true);
  say(!studio.song ? 'Planning every shot…'
    : (body.shaping || {}).arrange === 'fit' ? 'Finding the perfect fit of every kill to the song — this can take up to ~30 s…'
    : 'Finding the beat and planning every shot…');
  try {
    /* NOT OVER A RENDER IN PROGRESS. The plan took a minute, replaced the timeline of the reel
       being rendered, and then the server refused the render ("A reel is already rendering") --
       with the running render's progress lost from the page as well. A background render gives
       way to this one, so only a render somebody asked for holds it. */
    const job = await API.get('/api/studio/job').catch(() => null);
    if (gen !== studio.buildGen) return false;
    if (job && (job.state === 'running' || job.state === 'queued') && !job.auto) {
      const t = 'A reel is rendering now (' + Math.round(job.percent || 0) + '%). Make this one when it has finished: ' +
                'planning it now would replace the timeline of the reel being rendered.';
      if (o.held) o.held(t); else say(t, true);
      studio_poll();
      return false;
    }
    /* A rebuild keeps the reel's own choices -- facecam, handle, ending --
       which belong to the reel and not to the plan being redone. */
    if (ad && ad.keep) body.keep = Object.assign({}, body.keep || {}, ad.keep);
    const r = await API.post('/api/studio/plan', body);
    if (gen !== studio.buildGen) return false;    /* cancelled while planning */
    if (!r || !r.ok) { say((r && r.error) || 'Could not plan that reel.', true); return false; }
    studio_closeModals();
    /* A rebuild renders over the reel it rebuilds rather than beside it. */
    if (ad && ad.output) r.project.output = ad.output;
    /* A REBUILD OVER A REEL IS ONE STEP OF UNDO. It used to empty the history, so the timeline edits a
       rebuild replaced were gone for good the moment it landed; now Undo brings the reel back as it was. */
    const before = ad && ad.output && studio.project && studio.project.output === ad.output ? JSON.stringify(studio.project) : '';
    studio_flowForget(); studio.flow.ask = '';
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio.output = ad && ad.output ? ad.output : '';
    if (before) studio_pushUndo(before, 'Rebuilt from the clips');
    else { studio.undo = []; studio.redo = []; studio.playFile = ''; }
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
    return true;
  } finally {
    btn.disabled = false;
    studio.mkBuilding = false;
    studio_mkFlowDraw();
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
  if (project.output !== studio.output) studio.playFile = '';
  /* The analysis that came with a project is its song's, for the Song tab to draw it with. */
  if (songShape && songShape.beats && project.song) studio.shapes[project.song] = songShape;
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
  studio_flowForget();
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
  /* An edit of nothing the render draws -- a clip put in the reel's pool, shots locked together -- is
     a step of undo but not a change the video lacks. */
  if (paths && paths.length && !paths.some(studio_isEdit)) { studio_reconcile(); return; }
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
const STUDIO_NOT_EDITS = {output: 1, plan_notes: 1, lyrics_note: 1, render: 1, version: 1, remark: 1,
                          /* which render the reel is, and the clips waiting in its pool: neither is drawn */
                          render_version: 1, made_from: 1, checks: 1, selection: 1};
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
  studio_flowForget();
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
  /* The edits are one history; the renders are the other -- each a file of its own (studio_verHtml). */
  html += studio_verHtml();
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

/* ------------------------------------------------- every render, kept (clips/versions.py)

   A render used to replace the reel. Each one is a version of its own now, promoted to the reel only
   when it has finished, and History lists them -- what each was made from, which one the reel is --
   with Restore this version and Save as new reel. The player plays the version file itself, which is
   never written again, so a render finishing never has to wait for the player to let go of it. */
studio.versions = {list: [], current: 0, of: ''};

async function studio_verLoad() {
  const out = studio.output;
  if (!out) { studio.versions = {list: [], current: 0, of: ''}; studio_histDraw(); return; }
  const r = await API.get('/api/studio/versions?path=' + encodeURIComponent(out)).catch(() => null);
  if (out !== studio.output) return;
  studio.versions = r && r.ok ? {list: r.versions || [], current: r.current || 0, of: out} : {list: [], current: 0, of: out};
  studio_histDraw();
}

/* What a render was made from, in a line. */
function studio_verMade(m) {
  if (!m) return '';
  const st = (studio.catalog ? studio.catalog.styles : []).find(s => s.key === studio_styleNow(m.style));
  const bits = [st ? st.label : m.style, m.format === 'vertical' ? '9:16' : '16:9'];
  if (m.song) bits.push(m.song + (m.part ? ' ' + studio_partRange(m.part[0], m.part[1]) : ''));
  bits.push(m.shots + (m.shots === 1 ? ' shot' : ' shots'));
  if (m.length) bits.push(studio_dur(m.length));
  if (m.lyrics && m.lyrics !== 'off') bits.push('lyrics');
  return bits.join(' · ');
}

function studio_verHtml() {
  const v = studio.versions;
  if (!studio.output || v.of !== studio.output || !v.list.length) return '';
  return '<div class="studio-hist-head studio-ver-head"><h3>Renders</h3><span class="muted">' + v.list.length +
    (v.list.length === 1 ? ' version' : ' versions') + '</span></div>' +
    v.list.map(r => '<div class="studio-ver-row' + (r.current ? ' is-current' : '') + '" data-version="' + r.version + '">' +
      '<span class="studio-ver-name"><b>v' + r.version + '</b>' + (r.current ? ' <span class="studio-ver-now">the reel now</span>' : '') +
      (r.hard ? ' <span class="studio-ver-bad">check failed</span>' : '') + '</span>' +
      '<span class="muted studio-small">' + esc(studio_verMade(r.made_from)) + ' · ' + esc(studio_ago(r.when * 1000)) + '</span>' +
      '<span class="studio-ver-acts">' +
      (r.current ? '' : '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-ver-restore" data-v="' + r.version + '">Restore this version</button>') +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-ver-fork" data-v="' + r.version + '">Save as new reel</button>' +
      '</span></div>').join('');
}

/* RESTORE THIS VERSION: the reel becomes that render again -- the file and the project it was made from
   -- as one step of undo. Nothing is rendered. */
async function studio_verRestore(n) {
  const p = studio.project;
  if (!p || !studio.output || !n) return;
  const r = await API.post('/api/studio/version', {path: studio.output, version: n, action: 'restore'}).catch(() => null);
  if (!r || !r.ok) { toast((r && r.error) || 'That version could not be restored.', 'warn'); return; }
  studio_pushUndo(JSON.stringify(p), 'Render v' + n + ' restored');
  studio.gen++;
  studio_setProject(r.project, r.derived, r.notes, r.song);
  studio.output = r.project.output; studio.playFile = r.version_file || '';
  studio.renderedAt = Date.now(); studio.checksHard = 0;
  studio_settled();
  studio_loadVideo();
  studio_drawAll();
  studio_verLoad();
  toast('The reel is render v' + n + ' again.', 'ok');
}

/* SAVE AS NEW REEL: that render becomes a reel of its own, beside this one, and opens. */
async function studio_verFork(n) {
  const p = studio.project;
  if (!p || !studio.output || !n) return;
  const r = await API.post('/api/studio/version', {path: studio.output, version: n, action: 'fork',
                                                  name: (p.name || 'Reel') + ' v' + n}).catch(() => null);
  if (!r || !r.ok) { toast((r && r.error) || 'That version could not be saved as a reel.', 'warn'); return; }
  toast('Saved as a new reel: ' + r.name + '.', 'ok');
  studio.lib = null;
  await studio_open(r.path);
}

/* ------------------------------------------------- the reel's timing, resolved by the player

   WHAT HAPPENS WHEN THE PLAN NO LONGER MATCHES THE REEL. A part moved, a song changed, marks tapped
   again, drops moved: the reel's project carries a `draft` (clips/editflow.py) and its kill timing is
   STALE. Nothing re-plans on its own. The page says so in a banner nobody can miss, Render waits with
   the reason beside it, and the player picks one of:

     Replan for this section       the style's own planner on the new part, as a dry run, then a diff
     Keep my shots, retime them    the same shots, each kill placed on the new part's beats
     Undo part change              the draft dropped: the plan was never touched, so it holds again
     Re-snap my marks              the player's own marks moved with the part (only when there are any)

   A dry run carries the revision it was asked for (`rev`); any edit made while it runs bumps the
   revision, and an answer for an older one is dropped -- so a drag, a release and another drag can
   never apply what was planned for the first. Applying is one step of undo.

   The same machinery runs the three ways to update a reel (Re-render, Re-time, Replan) and the three
   things "Add clips..." can mean, each saying first what it keeps and what it changes -- the words
   come from the server's own table (studio.catalog.editflow). */
studio.flow = {rev: 0, busy: '', ask: '', askOpts: null, prop: null, conflicts: null, err: '', last: '', opts: null};

function studio_flowTable() { return (studio.catalog && studio.catalog.editflow) || {actions: {}, changes: []}; }
function studio_flowAction(kind) { return studio_flowTable().actions[kind] || {label: kind, says: '', keeps: [], changes: []}; }

/* Whether the reel on the timeline is waiting for its timing to be updated. */
function studio_reelStale() {
  const d = studio.project && studio.project.draft;
  return !!(d && Object.keys(d).length);
}

function studio_reelStaleWhy() {
  const why = studio_tmStale(studio_tmView('song'));
  const says = {song: 'The song changed', part: 'Song part changed', marks: 'Your kill marks changed', drops: 'The drops changed'};
  return why.length ? says[why[0]] + ' — kill timing needs updating' : '';
}

/* Any edit makes an answer about the reel before it an answer about a reel that is gone. */
function studio_flowForget() {
  const f = studio.flow;
  f.rev++;
  f.busy = ''; f.prop = null; f.conflicts = null; f.err = '';
}

function studio_partRange(a, b) { return studio_secs(a).replace(/\.\d+$/, '') + '–' + studio_secs(b).replace(/\.\d+$/, ''); }

/* THE STYLE BUILT ON A DROP, WITH ITS DROP OUTSIDE THE PART: it cannot be made, and the page says so
   before asking the server -- the same rule as editflow.drop_conflict. */
function studio_flowDropBlock() {
  const p = studio.project, sg = studio.sg;
  if (!p || !sg.shape) return null;
  const st = (studio.catalog ? studio.catalog.styles : []).find(s => s.key === p.style);
  if (!st || !st.drop) return null;
  const d = studio_tmMainDrop(studio_tmView('song'));
  if (d != null && d >= sg.start - 1e-3 && d <= sg.end + 1e-3) return null;
  return d != null
    ? {kind: 'drop-outside', text: 'This style is built on the drop, and the drop (' + studio_secs(d) + ') is outside the part.',
       fixes: [{fix: 'move-to-drop', label: 'Move the part to the drop'}, {fix: 'mark-drop', label: 'Mark a drop in this part'},
               {fix: 'other-style', label: 'Choose another style'}]}
    : {kind: 'drop-outside', text: 'This style is built on the drop, and this song has no drop marked.',
       fixes: [{fix: 'mark-drop', label: 'Mark a drop'}, {fix: 'other-style', label: 'Choose another style'}]};
}

/* A dry run of a re-time or a replan, for the part as it stands. Nothing is applied. */
async function studio_flowStart(kind, opts) {
  const p = studio.project, f = studio.flow, o = opts || {};
  if (!p) return;
  if (kind === 'rerender') { f.ask = ''; studio_flowDraw(); studio_render(); return; }
  if (studio.rendering) { toast('A reel is rendering. Update its timing once it has finished.', 'warn'); return; }
  const block = studio_reelStale() ? studio_flowDropBlock() : null;
  if (block) { f.conflicts = [block]; f.ask = ''; studio_flowDraw(); return; }
  const rev = ++f.rev;
  f.busy = kind; f.last = kind; f.opts = o; f.ask = ''; f.prop = null; f.conflicts = null; f.err = '';
  studio_drawRenderCard();
  const body = {project: p, rev: rev};
  if (kind === 'replan' && o.with) body.with = o.with;
  if (o.relax) body.relax = o.relax;
  if (o.add) body.add = true;
  const r = await API.post(kind === 'replan' ? '/api/studio/replan' : '/api/studio/retime', body).catch(() => null);
  if (rev !== f.rev || (r && r.rev !== undefined && r.rev !== rev)) return;     /* asked about a draft that is gone */
  f.busy = '';
  if (!r || !r.ok) f.err = (r && r.error) || 'That could not be worked out just now.';
  else if (r.conflicts && r.conflicts.length) f.conflicts = r.conflicts;
  else {
    const d = r.project.draft ? null : r.project;
    const part = d && d.song ? ' for ' + studio_partRange(d.song_offset || 0, d.part_end || (d.song_offset || 0) + r.derived.length) : '';
    const style = o.with && o.with.style ? (studio.catalog.styles.find(s => s.key === o.with.style) || {label: o.with.style}).label : '';
    f.prop = {kind: kind, project: r.project, derived: r.derived, notes: r.notes || [], diff: r.diff || {},
              room: r.room || null, song: r.song, opts: o,
              label: kind === 'retime' ? 'Shots re-timed' + part
                   : style ? 'Replanned as ' + style : o.with && o.with.clips ? 'Replanned with the clips you added' : 'Replanned' + part};
  }
  studio_drawRenderCard();
}

/* APPLY: the answer becomes the reel, as one step of undo. */
function studio_flowApply() {
  const f = studio.flow, pr = f.prop, p = studio.project;
  if (!pr || !p) return;
  const snapshot = JSON.stringify(p);
  studio_pushUndo(snapshot, pr.label);
  studio.gen++;
  pr.project.output = p.output;
  f.prop = null; f.rev++;
  studio_setProject(pr.project, pr.derived, pr.notes, pr.song === undefined ? undefined : pr.song);
  studio_touched(pr.label, -1, studio_diff(JSON.parse(snapshot), pr.project));
  studio_fit();
  studio_drawAll();
  toast(pr.label + '. Render to see it.', 'ok');
}

function studio_flowDiscard() {
  const f = studio.flow;
  f.prop = null; f.conflicts = null; f.err = ''; f.ask = '';
  studio_drawRenderCard();
}

/* UNDO PART CHANGE: the exact spec before it. The plan was never touched while the part was stale, so
   with the part back the plan holds again at once -- nothing is planned or re-timed. One edit, which
   undo can take back too. */
function studio_flowUndo(what) {
  const keys = what === 'marks' ? ['marks'] : what === 'drops' ? ['drops'] : ['start', 'end', 'song'];
  const label = what === 'marks' ? 'Mark changes undone' : what === 'drops' ? 'Drop changes undone' : 'Part change undone';
  studio_flowForget();
  studio_change(p => {
    const d = Object.assign({}, p.draft || {});
    keys.forEach(k => { delete d[k]; });
    if (Object.keys(d).length) p.draft = d; else delete p.draft;
  }, label);
}

/* The nearest of the song's hits within half a beat, else the nearest beat: where a moved mark lands. */
function studio_tmHit(sh, t) {
  if (!sh) return t;
  const beat = sh.beat || 60 / sh.bpm;
  let best = null, gap = beat / 2 + 1e-6;
  (sh.hits || []).forEach(h => { const g = Math.abs(h - t); if (g < gap) { gap = g; best = h; } });
  return best != null ? best : studio_nearestBeat(sh, t);
}

/* RE-SNAP MY MARKS: the player's own marks moved with the part, by as far as it moved, each onto the
   new section's nearest hit. The one thing that ever moves a hand mark, and only when asked. */
function studio_flowResnap() {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  const dt = sg.start - (p.song_offset || 0);
  studio_tmOwn(sg);
  let n = 0;
  sg.hand.forEach(k => { if (!k.auto) { k.t = Math.round(studio_tmHit(sg.shape, k.t + dt) * 1000) / 1000; n++; } });
  if (!n) { toast('None of the marks are yours: AutoStream places its own again anyway.', 'warn'); return; }
  sg.hand.sort((x, y) => x.t - y.t);
  /* the anchors go with them */
  const moved = sg.hand.filter(k => !k.auto).map(k => k.t);
  studio_change(q => { studio_tmWriteReel(q, sg); q.anchors = moved; }, 'Your marks moved with the part');
}

function studio_flowFix(fix, el) {
  const f = studio.flow, sg = studio.sg;
  f.conflicts = null;
  if (fix === 'resnap') { studio_flowResnap(); studio_flowStart(f.last || 'retime'); return; }
  if (fix === 'forget-outside') {
    studio_change(p => { p.anchors = (p.anchors || []).filter(a => a >= sg.start - 1e-3 && a <= sg.end + 1e-3); }, 'Your marks outside the part forgotten');
    studio_flowStart(f.last || 'retime');
    return;
  }
  if (fix === 'longer-part') {
    const end = Number(el && el.getAttribute('data-end'));
    if (isFinite(end) && sg.shape) { sg.end = Math.min(sg.shape.seconds, end); studio_sgCommit('The part made longer'); }
    studio_flowStart('retime');
    return;
  }
  if (fix.indexOf('relax:') === 0) { studio_flowStart('retime', {relax: fix.slice(6)}); return; }
  if (fix === 'add') { studio_flowStart('retime', {add: true}); return; }
  if (fix === 'move-to-drop') { studio_sgAtDrop(); return; }
  if (fix === 'mark-drop') {
    studio_tab('song');
    toast('Double-click the top lane of the part up close, where you hear the bass come in, to mark the drop.');
    return;
  }
  if (fix === 'other-style') { studio_flowAsk('replan', {chooseStyle: true}); return; }
  studio_drawRenderCard();
}

/* BEFORE ANYTHING RUNS, WHAT IT KEEPS AND WHAT IT CHANGES. */
function studio_flowAsk(kind, opts) {
  const f = studio.flow;
  f.ask = kind; f.askOpts = opts || {}; f.prop = null; f.conflicts = null; f.err = '';
  if (studio_el('studio-pane-timeline').classList.contains('hide') && kind !== 'add') studio_tab('timeline');
  studio_drawRenderCard();
  const host = studio_el('studio-tl-stale');
  if (host && host.scrollIntoView) host.scrollIntoView({block: 'nearest'});
}

function studio_flowList(items) { return '<ul>' + items.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>'; }

function studio_flowKeeps(kind) {
  const a = studio_flowAction(kind);
  return '<div class="studio-flow-cols"><div><b>Keeps</b>' + studio_flowList(a.keeps || []) + '</div>' +
    '<div><b>Changes</b>' + studio_flowList(a.changes || []) + '</div></div>';
}

function studio_flowBtn(act, label, opts) {
  const o = opts || {};
  return '<button type="button" class="btn ' + (o.primary ? 'btn-primary ' : o.ghost ? 'btn-ghost ' : '') + 'btn-sm' +
    (o.attn ? ' studio-attn' : '') + '" data-act="' + act + '"' + (o.do ? ' data-do="' + o.do + '"' : '') +
    (o.how ? ' data-how="' + o.how + '"' : '') + (o.disabled ? ' disabled' : '') +
    (o.title ? ' title="' + esc(o.title) + '"' : '') + '>' + esc(label) + '</button>';
}

/* The proposal: what applying it would change, in the terms the player decides on. */
function studio_flowPropHtml(pr) {
  const d = pr.diff || {}, a = d.shots || [0, 0], len = d.length || [0, 0];
  const facts = [];
  facts.push('Shots: ' + a[0] + (a[1] !== a[0] ? ' → ' + a[1] : ', all kept'));
  if ((d.clips_in || []).length) facts.push('Clips coming in: ' + d.clips_in.slice(0, 6).join(', ') + (d.clips_in.length > 6 ? '…' : ''));
  if ((d.clips_out || []).length) facts.push('Clips going out: ' + d.clips_out.slice(0, 6).join(', ') + (d.clips_out.length > 6 ? '…' : ''));
  facts.push('Kills: ' + (d.kills_moved || 0) + ' moved, ' + (d.kills_kept || 0) + ' where they were' +
             (d.kills_new ? ', ' + d.kills_new + ' new' : '') + (d.kills_gone ? ', ' + d.kills_gone + ' left out' : ''));
  facts.push('Length: ' + studio_dur(len[0]) + (Math.abs(len[1] - len[0]) > 0.05 ? ' → ' + studio_dur(len[1]) : ''));
  const om = d.on_marks || [0, 0];
  facts.push('Kills on their marks: ' + om[1] + ' of ' + a[1] + (om[1] !== om[0] ? ' (was ' + om[0] + ')' : ''));
  if (d.effects_kept) facts.push('Your effects kept on ' + d.effects_kept + ' shot' + (d.effects_kept === 1 ? '' : 's'));
  if (d.marks_outside) facts.push(d.marks_outside + ' of your marks are outside this part and could not be used');
  if (pr.kind === 'replan' && d.edited) facts.push('Your timeline edits are replaced on every shot the new plan does not keep');
  const notes = (pr.notes || []).slice(0, 4);
  return '<div class="studio-flow is-prop" role="region" aria-label="What this would change">' +
    '<p class="studio-flow-head">' + esc(pr.label) + ' — apply it?</p>' +
    '<p class="muted studio-small">Worked out, not applied. The reel is as it was until you apply this; applying it is one step of undo.</p>' +
    studio_flowList(facts) +
    (notes.length ? '<details class="studio-fold"><summary>What the ' + (pr.kind === 'retime' ? 're-time' : 'plan') + ' said</summary>' + studio_flowList(notes) + '</details>' : '') +
    (pr.room ? '<p class="studio-flow-room">The part has room for ' + pr.room.marks + ' more kill' + (pr.room.marks === 1 ? '' : 's') +
               ' after the last shot. <button type="button" class="btn btn-sm" data-act="studio-flow-fix" data-fix="add">Add shots from this reel’s clips</button></p>' : '') +
    '<div class="studio-flow-acts">' + studio_flowBtn('studio-flow', 'Apply', {primary: true, do: 'apply'}) +
    studio_flowBtn('studio-flow', 'Discard', {ghost: true, do: 'discard'}) + '</div></div>';
}

function studio_flowConflictHtml(list) {
  return '<div class="studio-flow is-bad" role="alert">' +
    '<p class="studio-flow-head">This cannot be done as it stands</p>' +
    list.map(c => '<p>' + esc(c.text) + '</p><div class="studio-flow-acts">' +
      (c.fixes || []).map(x => '<button type="button" class="btn btn-sm" data-act="studio-flow-fix" data-fix="' + esc(x.fix) + '"' +
        (x.end !== undefined ? ' data-end="' + x.end + '"' : '') + '>' + esc(x.label) + '</button>').join('') + '</div>').join('') +
    '<div class="studio-flow-acts">' + studio_flowBtn('studio-flow', 'Close', {ghost: true, do: 'discard'}) + '</div></div>';
}

/* "ADD CLIPS..." SAYS WHICH. It used to be a rebuild in all but name: back to the clips, then the Make
   page, then every shot planned again. Now it is one of three, each saying what it does to the reel. */
function studio_flowAddHtml() {
  const p = studio.project, d = studio.derived, i = studio.sel;
  const shot = p && i >= 0 && i < p.shots.length ? p.shots[i] : null;
  const rp = studio_flowAction('replan');
  return '<div class="studio-flow is-ask" role="region" aria-label="Add clips">' +
    '<p class="studio-flow-head">Add clips to ' + esc(p.name || 'this reel') + '</p>' +
    '<div class="studio-flow-choice"><b>Add them to the reel’s pool</b>' +
      '<p class="muted studio-small">Every shot stays as it is. The clips wait in the pool, for "Add shots" when a part has room, or for a replan.</p>' +
      studio_flowBtn('studio-add-how', 'Pick clips for the pool', {how: 'pool'}) + '</div>' +
    '<div class="studio-flow-choice"><b>Replace ' + (shot ? esc(studio_shotName(i)) + '’s clip' : 'a shot’s clip') + '</b>' +
      '<p class="muted studio-small">' + (shot ? 'Keeps its place, its length and its effects (' + esc(shot.name || '') +
        ' now); its kill is re-timed onto its mark. The shots around it do not change.' : 'Select a shot on the timeline first.') + '</p>' +
      studio_flowBtn('studio-add-how', 'Pick its new clip', {how: 'replace', disabled: !shot, title: shot ? '' : 'Select a shot on the timeline first.'}) + '</div>' +
    '<div class="studio-flow-choice"><b>Replan with these clips</b>' +
      '<p class="muted studio-small">' + esc(rp.says ? rp.says[0].toUpperCase() + rp.says.slice(1) : 'Plans the reel again') + ', with every setting on the Make page.' +
        (d && d.edited ? ' Your timeline edits are replaced on shots the new plan does not keep.' : '') + '</p>' +
      studio_flowKeeps('replan') + studio_flowBtn('studio-add-how', 'Pick clips, then replan', {how: 'replan'}) + '</div>' +
    '<div class="studio-flow-acts">' + studio_flowBtn('studio-flow', 'Cancel', {ghost: true, do: 'discard'}) + '</div></div>';
}

function studio_flowAskHtml() {
  const f = studio.flow, k = f.ask, a = studio_flowAction(k), p = studio.project, d = studio.derived;
  if (k === 'add') return studio_flowAddHtml();
  const stale = studio_reelStale();
  let extra = '', go = '';
  if (k === 'rerender') {
    go = studio_flowBtn('studio-flow', 'Re-render', {primary: true, do: 'rerender', disabled: stale,
                        title: stale ? studio_reelStaleWhy() + ': update the timing first.' : ''});
    if (stale) extra = '<p class="studio-flow-why">' + esc(studio_reelStaleWhy()) + ': update the timing first.</p>';
  } else if (k === 'retime') {
    go = studio_flowBtn('studio-flow', 'Re-time the shots', {primary: true, do: 'retime'});
  } else {
    const styles = (studio.catalog ? studio.catalog.styles : []);
    const want = (f.askOpts && f.askOpts.style) || p.style;
    extra = '<label class="field-label" for="studio-flow-style">Style</label><select class="select" id="studio-flow-style">' +
      styles.map(s => '<option value="' + esc(s.key) + '"' + (s.key === want ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('') + '</select>' +
      (d && d.edited ? '<p class="studio-flow-why">You have edited this reel’s timeline since it was planned: those edits are replaced on every shot the new plan does not keep.</p>' : '');
    go = studio_flowBtn('studio-flow', 'Replan', {primary: true, do: 'replan'});
  }
  return '<div class="studio-flow is-ask" role="region" aria-label="' + esc(a.label) + '">' +
    '<p class="studio-flow-head">' + esc(a.label) + ' — ' + esc(a.says) + '</p>' + studio_flowKeeps(k) + extra +
    '<div class="studio-flow-acts">' + go + studio_flowBtn('studio-flow', 'Cancel', {ghost: true, do: 'discard'}) + '</div></div>';
}

/* THE BANNER: why the timing is stale and what to do about it. The way to resolve it most people want
   -- a plan of its own for the new section -- is the one that cannot be missed: the primary button, in
   the accent, with a slow glow (still, for anyone who has asked for less motion). */
function studio_flowStaleHtml() {
  const p = studio.project, sg = studio.sg, why = studio_tmStale(studio_tmView('song'));
  const block = studio_flowDropBlock();
  const s0 = p.song_offset || 0, e0 = p.part_end > s0 ? p.part_end : s0 + ((studio.derived && studio.derived.length) || 0);
  const mine = (p.anchors || []).length > 0;
  let sub = '', acts = '';
  const no = block ? {disabled: true, title: 'The drop is outside the part: ' + block.fixes.map(x => x.label.toLowerCase()).join(', or ') + ' first.'} : {};
  if (why.indexOf('song') >= 0 || why.indexOf('part') >= 0) {
    sub = why.indexOf('song') >= 0
      ? 'The kills are still timed for ' + esc((p.song || 'no song').split(/[\\/]/).pop()) + '. Render waits until the timing matches.'
      : 'The kills are still timed for ' + studio_partRange(s0, e0) + ' (dashed); the part is now ' +
        studio_partRange(sg.start, sg.end) + '. Render waits until they match.';
    acts = studio_flowBtn('studio-flow', 'Replan for this section', Object.assign({primary: true, attn: !block, do: 'replan'}, no)) +
      studio_flowBtn('studio-flow', 'Keep my shots, retime them', Object.assign({do: 'retime'}, no)) +
      studio_flowBtn('studio-flow', why.indexOf('song') >= 0 ? 'Undo song change' : 'Undo part change', {ghost: true, do: 'undo'}) +
      (mine ? studio_flowBtn('studio-flow', 'Re-snap my marks', {ghost: true, do: 'resnap',
              title: 'Move the marks you placed with the part, each onto the new section’s nearest hit'}) : '');
  } else if (why.indexOf('marks') >= 0) {
    sub = 'The shots are still cut to the marks they were planned on. Render waits until they are re-timed to yours.';
    acts = studio_flowBtn('studio-flow', 'Re-time to my marks', {primary: true, attn: true, do: 'retime'}) +
      studio_flowBtn('studio-flow', 'Undo mark changes', {ghost: true, do: 'undo-marks'});
  } else {
    const st = (studio.catalog ? studio.catalog.styles : []).find(s => s.key === p.style);
    sub = 'The kills were placed around the drops as they were. Render waits until the timing matches.';
    acts = (st && st.drop
      ? studio_flowBtn('studio-flow', 'Replan around the drops', Object.assign({primary: true, attn: !block, do: 'replan'}, no))
      : studio_flowBtn('studio-flow', 'Re-time to the drops', {primary: true, attn: true, do: 'retime'}) +
        studio_flowBtn('studio-flow', 'Replan for this section', {do: 'replan'})) +
      studio_flowBtn('studio-flow', 'Undo drop changes', {ghost: true, do: 'undo-drops'});
  }
  return '<div class="studio-flow is-stale" role="alert" data-why="' + esc(why.join(' ')) + '">' +
    '<p class="studio-flow-head">' + esc(studio_reelStaleWhy()) + '</p><p class="studio-small">' + sub + '</p>' +
    (block ? '<p class="studio-flow-why">' + esc(block.text) + '</p><div class="studio-flow-acts">' +
      block.fixes.map(x => '<button type="button" class="btn btn-sm" data-act="studio-flow-fix" data-fix="' + esc(x.fix) + '">' + esc(x.label) + '</button>').join('') + '</div>' : '') +
    '<div class="studio-flow-acts">' + acts + '</div></div>';
}

function studio_flowHtml() {
  const p = studio.project, f = studio.flow;
  if (!p) return '';
  if (f.busy) {
    return '<div class="studio-flow is-busy" role="status"><p class="studio-flow-head">' +
      (f.busy === 'replan' ? 'Planning the reel for this section…' : 'Re-timing your shots…') + '</p>' +
      '<p class="muted studio-small">The reel stays as it is until you apply what comes back. A change you make meanwhile makes this answer old, and it is dropped.</p>' +
      '<div class="studio-flow-acts">' + studio_flowBtn('studio-flow', 'Stop', {ghost: true, do: 'stop'}) + '</div></div>';
  }
  if (f.prop) return studio_flowPropHtml(f.prop);
  if (f.conflicts) return studio_flowConflictHtml(f.conflicts);
  if (f.err) {
    return '<div class="studio-flow is-bad" role="alert"><p class="studio-flow-head">' + esc(f.err) + '</p><div class="studio-flow-acts">' +
      studio_flowBtn('studio-flow', 'Try again', {do: f.last || 'replan'}) + studio_flowBtn('studio-flow', 'Close', {ghost: true, do: 'discard'}) + '</div></div>';
  }
  if (f.ask) return studio_flowAskHtml();
  if (studio_reelStale()) return studio_flowStaleHtml();
  return '';
}

/* Drawn into every place that shows the reel's timing: the Song tab, and the timeline's side panel --
   so the same banner, and the same buttons, are wherever the player is looking. */
function studio_flowDraw() {
  const html = studio_flowHtml();
  /* What is asked before an update runs, and "Add clips...", belong to the timeline's panel only: the
     Song tab shows the timing's own banner, and one set of controls has one set of ids. */
  const f = studio.flow, song = f.ask && !f.busy && !f.prop && !f.conflicts && !f.err
    ? (studio.project && studio_reelStale() ? studio_flowStaleHtml() : '') : html;
  ['studio-sg-stale', 'studio-tl-stale'].forEach(id => {
    const el = studio_el(id);
    if (!el) return;
    const html2 = id === 'studio-sg-stale' ? song : html;
    /* A stale banner already showing is left alone, so the glow is not restarted on every redraw. */
    if (el.getAttribute('data-html') === html2) return;
    el.setAttribute('data-html', html2);
    el.innerHTML = html2;
    el.classList.toggle('hide', !html2);
  });
  const stale = studio_reelStale(), rp = studio_el('studio-tl-replan');
  if (rp) {
    const block = stale ? studio_flowDropBlock() : null;
    rp.classList.toggle('hide', !stale || !!studio.flow.busy || !!studio.flow.prop);
    rp.disabled = !!block;
    rp.title = block ? block.text : studio_reelStaleWhy() + ': plan the reel again for the new part';
  }
  studio_mkFlowDraw();
}

function studio_flowAct(b) {
  const what = b.getAttribute('data-do'), f = studio.flow;
  if (what === 'apply') return studio_flowApply();
  if (what === 'discard') return studio_flowDiscard();
  if (what === 'stop') { studio_flowForget(); return studio_drawRenderCard(); }
  if (what === 'undo') return studio_flowUndo('part');
  if (what === 'undo-marks') return studio_flowUndo('marks');
  if (what === 'undo-drops') return studio_flowUndo('drops');
  if (what === 'resnap') return studio_flowResnap();
  if (what === 'rerender') return studio_flowStart('rerender');
  if (what === 'retime') return studio_flowStart('retime', f.err && f.last === 'retime' ? f.opts : {});
  if (what === 'replan') {
    const sel = studio_el('studio-flow-style');
    const style = f.ask === 'replan' && sel ? sel.value : '';
    return studio_flowStart('replan', style && style !== studio.project.style ? {with: {style: style}} : {});
  }
}

/* THE STATE OF THE REEL, ALWAYS IN VIEW: one word for where it stands, and why when it is held. */
const STUDIO_BADGES = {
  changed: 'Changed', stale: 'Timing stale', planning: 'Planning', ready: 'Ready to render',
  rendering: 'Rendering', rendered: 'Rendered', failed: 'Check failed'
};

function studio_badgeState() {
  if (!studio.project) return null;
  if (studio.rendering || studio.auto.running) return {key: 'rendering', why: studio.jobMsg || 'The reel is rendering.'};
  if (studio.flow.busy) return {key: 'planning', why: studio.flow.busy === 'replan' ? 'Planning the reel for the part.' : 'Re-timing the shots.'};
  if (studio_reelStale()) return {key: 'stale', why: studio_reelStaleWhy() + '. Render waits until it is updated.'};
  if (studio.failMsg || studio.checksHard) return {key: 'failed', why: studio.failMsg || 'The finished reel did not pass its check.'};
  if (!studio.output) return {key: 'ready', why: 'Planned; nothing rendered yet.'};
  if (studio.dirty) return {key: 'changed', why: studio_pendingCount() + ' change(s) not in the video yet.'};
  return {key: 'rendered', why: 'The video matches the reel.'};
}

function studio_badgeHtml(st) {
  return st ? '<span class="studio-badge-dot" aria-hidden="true"></span>' + esc(STUDIO_BADGES[st.key]) : '';
}

function studio_badgeDraw() {
  const el = studio_el('studio-badge'), st = studio_badgeState();
  if (!el) return;
  el.className = 'studio-badge' + (st ? ' is-' + st.key : '');
  el.setAttribute('data-state', st ? st.key : '');
  el.title = st ? st.why : '';
  el.innerHTML = studio_badgeHtml(st);
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
                 pieces: old.pieces || [[0, s.duration, 1]],
                 /* Carried, not known: studio_pvInfo trusts only a row the
                    server's derive made, and this says which these are. */
                 estimate: true};
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
  /* A version file is never replaced, so the previous render keeps playing while the next one runs. */
  if (studio.playFile) return;
  try {
    v.pause();
    v.removeAttribute('src');
    v.load();                       /* without this the handle survives */
  } catch (e) { /* a player that will not let go is the server's problem */ }
}

async function studio_render() {
  if (!studio.project) return;
  /* The server refuses it too (editflow.can_render); this is only so nothing is let go of for it. */
  if (studio_reelStale()) { toast(studio_reelStaleWhy() + '. Update it first.', 'warn'); studio_drawRenderCard(); return; }
  studio_freeOutput();
  /* A check still waiting or in flight describes the project before the
     server allocates its output; letting it land afterwards would wipe that. */
  clearTimeout(studio.checkTimer);
  studio.gen++;
  /* The previous render is old news once a new one is asked for: a poll that
     lands in between must not say "Ready" about the reel being replaced. Unless
     the server refuses this one -- then the render still running is still news,
     and forgetting it lost its progress and its "Reel ready". */
  const wasSeen = studio.seenJob, wasWatching = studio.watching;
  studio.seenJob = studio.jobId; studio.watching = -1;
  studio.checksHard = 0;
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
    studio.seenJob = wasSeen; studio.watching = wasWatching;
    studio.pending = sent.concat(studio.pending); studio.base = sentBase; studio.dirty = studio.pending.length > 0;
    studio_state((r && r.error) || 'Could not start the render.', true);
    studio_drawRenderCard();
    studio_poll();                  /* a render already running is followed again */
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
    studio.checksHard = (j.checks || []).filter(c => c && c.level === 'hard').length;
    if (same) {
      /* Not studio_settled(): an edit made while the render ran is a real
         difference from the video that has just arrived, and saying otherwise
         would lose it. studio_render() already cleared what it sent. */
      studio.output = j.output; studio.renderedAt = Date.now(); studio.playFile = j.version_file || '';
      studio_verLoad();
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
      studio.output = j.output; studio.renderedAt = Date.now(); studio.playFile = j.version_file || '';
      studio.checksHard = (j.checks || []).filter(c => c && c.level === 'hard').length;
      if (fresh) studio_settled();
      studio_loadVideo();
      studio_verLoad();
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
  studio_el('studio-render-btn').disabled = on || studio_reelStale();
  studio_show('studio-meter-wrap', on);
}

function studio_loadVideo() {
  const v = studio_el('studio-video');
  if (!studio.output) { v.removeAttribute('src'); studio_show('studio-player-empty', true); return; }
  /* The render's own version file when known: it is never written again, so nothing waits for the
     player to let go of it (clips/versions.py). */
  v.src = studio_media('/api/clips/video', studio.playFile || studio.output, '&v=' + studio.renderedAt);
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
                         s.kills || []]);
}

/* The server's account of shot i's footage: where it starts in the clip and
   its speed map. Only the server's derive knows them; while the page's own
   quick estimate stands in (a drag, the quarter second before /check
   answers -- its rows say `estimate`), a shot nothing has changed about
   keeps what the server said last time, and a shot being changed plays at
   real speed from where its kill puts it. */
function studio_pvInfo(i) {
  const p = studio.project, d = studio.derived;
  const s = p && p.shots[i], r = d && d.shots[i];
  if (!s || !r) return null;
  const key = studio_pvKey(s);
  if (r.source_in !== undefined && r.pieces !== undefined && !r.estimate) {
    const got = {source_in: r.source_in, pieces: r.pieces};
    studio.pv.info[key] = got;
    return got;
  }
  return studio.pv.info[key] ||
    {source_in: Math.max(0, s.kill - s.pre), pieces: [[0, s.duration, 1]]};
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
  const held = u >= dur;
  u = Math.min(u, dur);
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
                                                     r.source_in])) + '|' + d.length;
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
  if (studio_reelStale()) { a.held = 'Waiting: the kill timing needs updating.'; return; }
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
  let held = studio.rendering ? 'Waiting for the render you started.'
    : studio_reelStale() ? 'Waiting: the kill timing needs updating.' : studio_autoBusyElsewhere();
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
  if (!a.on || !studio.project || !studio.dirty || a.timer || a.running || studio.rendering || studio_reelStale()) return;
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
  studio_flowDraw();
  studio_badgeDraw();
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
  } else if (studio_reelStale()) {
    /* NEVER A RENDER OF A PLAN THE REEL HAS MOVED PAST. The button is not taken away -- it says why it
       is held, and the fix is beside it and in the banner below. */
    kind = 'timing'; label = 'Render';
    head = studio_reelStaleWhy();
    sub = 'Render waits until the kill timing matches: replan for this section, or keep your shots and re-time them.';
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
    btn.classList.toggle('btn-primary', kind !== 'stale' && kind !== 'timing');
    btn.disabled = studio.rendering || kind === 'timing';
    btn.title = kind === 'timing' ? head + '. Replan for this section, or keep your shots and re-time them, first.' : '';
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
    /* Not over the preview: that IS the edits, and says what it leaves out -- except when the timing
       is stale, when both the video and the preview are the timing that no longer holds. */
    if (kind === 'timing') {
      studio_show('studio-stale', true);
      stale.textContent = (studio.output ? 'Previous render' : 'Preview') + ' · the kill timing is out of date';
    } else {
      studio_show('studio-stale', kind === 'stale' && !!studio.output && !studio_pvWanted());
      stale.textContent = 'Last render · ' + n + (n === 1 ? ' change not shown' : ' changes not shown');
    }
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

/* BACK TO THE CLIPS, TO ADD SOME -- one of three ways, chosen first (studio_flowAddHtml):

     pool       the clips join the reel's pool; no shot changes
     replace    one clip replaces the selected shot's; it keeps its place, length and effects
     replan     the reel planned again with them, on the Make page, every setting carried

   For a replan the reel's clips are picked already, so the ones added are seen beside them; for the
   other two nothing is, so what is picked is exactly what is added. What a rebuild asks for is the
   reel's SPEC: a part moved and not yet planned for is the part it plans. */
async function studio_addClips(how) {
  const p = studio.project, d = studio.derived, mode = how || 'replan';
  if (!p) return;
  if (mode === 'replace' && !(studio.sel >= 0 && studio.sel < p.shots.length)) { toast('Select a shot on the timeline first.', 'warn'); return; }
  studio.flow.ask = '';
  await studio_load(false);
  const want = (p.selection && p.selection.length) ? p.selection.map(x => x.clip) : p.shots.map(x => x.clip);
  const byPath = {};
  Object.keys(studio.clipIndex).forEach(id => { byPath[String(studio.clipIndex[id].path).toLowerCase()] = id; });
  const ids = [];
  want.forEach(path => {
    const id = byPath[String(path).toLowerCase()];
    if (id && ids.indexOf(id) < 0) ids.push(id);
  });
  studio.selected = mode === 'replan' ? ids : [];
  studio_syncSelection();
  const dr = p.draft || {};
  const start = dr.start !== undefined ? dr.start : (p.song_offset || 0);
  studio.adding = {
    mode: mode, shot: studio.sel,
    name: p.name, style: p.style, song: dr.song !== undefined ? dr.song : (p.song || ''), fmt: p.format,
    output: studio.output || p.output || '',
    start: start, end: dr.end !== undefined ? dr.end : (p.part_end || (start + (d ? d.length : 0))),
    fill: p.fill || '', keep_all: !!p.keep_all,
    edited: !!(d && d.edited) || studio.undo.length > 0,
    keep: {cam: p.cam, vfit: p.vfit, handle: p.handle, handle_pos: p.handle_pos,
           outro_len: p.outro_len, overlays: p.overlays, lyrics: p.lyrics},
    /* WHAT THE PLAYER CHOSE, ASKED AGAIN. A rebuild of a Build and drop reel built on whichever
       set-up scored best, held the page's own part to an end, and dropped the intro, Headshots
       only and any drops marked by hand -- none of them were carried. The project keeps them,
       and the player's own kill marks too: the rebuild plans around them. */
    build_clip: p.build_clip || '', part_auto: !!p.part_auto && dr.start === undefined, hs_only: !!p.hs_only,
    intro_clip: p.intro_clip && p.intro_clip.path ? {path: p.intro_clip.path, audio: !!p.intro_clip.audio} : null,
    drops: dr.drops !== undefined ? (dr.drops ? dr.drops.slice() : null) : (Array.isArray(p.hand_drops) ? p.hand_drops.slice() : null),
    anchors: (p.anchors || []).slice(), marks: dr.marks ? dr.marks.slice() : null
  };
  studio_tab('clips');
  studio_renderLib();
  if (mode === 'replan' && ids.length < new Set(want).size) toast('Some of the clips in this reel are not in the clips folder any more.', 'warn');
  if (mode === 'replace') toast('Pick the clip for ' + studio_shotName(studio.sel) + ', then "Use this clip".');
}

/* The pool or a shot's clip, from the clips picked: an edit of the reel, back on the timeline. */
function studio_addGo() {
  const ad = studio.adding, p = studio.project;
  if (!ad || !p) return;
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  if (ad.mode === 'pool') {
    const have = new Set((p.selection || []).map(r => String(r.clip).toLowerCase())
                          .concat(p.shots.map(s => String(s.clip).toLowerCase())));
    const add = sel.filter(c => !have.has(String(c.path).toLowerCase()));
    if (!add.length) { toast(sel.length ? 'Those clips are in this reel already.' : 'Pick the clips to add first.', 'warn'); return; }
    studio_change(q => {
      const rows = (q.selection && q.selection.length) ? q.selection.slice()
        : Array.from(new Set(q.shots.map(s => s.clip))).map(c => ({clip: c, name: (q.shots.find(s => s.clip === c) || {}).name || ''}));
      q.selection = rows.concat(add.map(c => ({clip: c.path, name: c.name || '', why: 'In the pool, not in the reel yet.'})));
    }, add.length + (add.length === 1 ? ' clip added to the pool' : ' clips added to the pool'));
    toast(add.length + (add.length === 1 ? ' clip is' : ' clips are') + ' in the pool now. Every shot is as it was.', 'ok');
  } else if (ad.mode === 'replace') {
    if (sel.length !== 1) { toast('Pick exactly one clip for the shot.', 'warn'); return; }
    const c = sel[0], i = ad.shot;
    if (!p.shots[i]) { toast('That shot is not in the reel any more.', 'warn'); return; }
    const kills = (c.kills || []).slice(), k = kills.length ? kills[0] : (c.duration || 2) / 2;
    studio_change(q => {
      const s = q.shots[i];
      /* the place, the length, the run-up and every effect stay; the footage and its kills are the new clip's */
      Object.assign(s, {clip: c.path, clip_id: '', name: c.name || '', kill: k, kills: kills.length ? kills : [k],
                        clip_seconds: 0, clip_mtime: 0});
      delete s.stretch; delete s.anchors; delete s.led;
      /* ...and its kill goes back onto its mark: the local re-time the table names */
      studio_remark(q);
    }, studio_shotName(i) + ': its clip replaced', i);
  } else {
    return;
  }
  studio.adding = null; studio.selected = []; studio_syncSelection();
  studio_renderTray();
  studio_tab('timeline');
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
  /* The Song tab is the reel's draft, read from the project: an undo, an edit or an answer redraws it. */
  if (!studio_el('studio-pane-song').classList.contains('hide')) { studio_sgSync(); studio_sgReset(); }
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
   of "K02 · Shake" lines and walls of forty checkboxes -- names nobody had
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
      : '<p class="muted studio-fxp-none">Nothing matches “' + esc(q) + '”. Try a shorter word, or a code like K02.</p>';
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
      '<button type="button" class="btn btn-sm studio-add-btn" data-act="studio-restyle" id="studio-restyle-btn"' + (studio.busy ? ' disabled' : '') + '>Replan with this style&hellip;</button>' +
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
  studio.playFile = r.version_file || ''; studio.checksHard = 0;
  studio_flowForget(); studio.flow.ask = '';
  studio_settled();
  studio.renderNote = '';
  studio_tab('timeline');
  studio_fit();
  studio_drawAll();
  studio_loadVideo();
  studio_verLoad();
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
    else if (act === 'studio-preview-close') studio_previewClose();
    else if (act === 'studio-make-cancel') studio_buildCancel();
    else if (act === 'studio-clear') { studio.selected = []; studio.adding = null; studio_syncSelection(); }
    /* THE STEPS ARE THE WAY IN (F13, the player's call once a second style passed its review):
       the clips picked here open the guided maker with them in it. Rebuilding a reel still opens
       the full page with that reel's settings, and All settings is on every step of the guide. */
    else if (act === 'studio-make') {
      if (studio.adding && studio.adding.mode && studio.adding.mode !== 'replan') studio_addGo();
      else if (studio.adding) studio_openMake();
      else studio_gdOpenWith(studio.selected.slice());
    }
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
      studio_mkFootageDraw();
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
    else if (act === 'studio-add') studio_flowAsk('add');
    else if (act === 'studio-add-how') studio_addClips(b.getAttribute('data-how'));
    else if (act === 'studio-add-go') studio_addGo();
    else if (act === 'studio-flow') studio_flowAct(b);
    else if (act === 'studio-flow-fix') studio_flowFix(b.getAttribute('data-fix'), b);
    else if (act === 'studio-flow-ask') studio_flowAsk(b.getAttribute('data-do'));
    else if (act === 'studio-ver-restore') studio_verRestore(Number(b.getAttribute('data-v')));
    else if (act === 'studio-ver-fork') studio_verFork(Number(b.getAttribute('data-v')));
    else if (act === 'studio-mk-flow') studio_mkFlowAct(b);
    else if (act === 'studio-mk-guide') studio_mkToGuide();
    else if (act === 'studio-mk-lyrics') studio_mkLyrics(b.getAttribute('data-v'));
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
      if (studio.histOpen) studio_verLoad();
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
    else if (act === 'studio-restyle' && p) { const sel = studio_el('studio-r-style'); studio_flowAsk('replan', {style: sel ? sel.value : ''}); }
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
    else if (act === 'studio-sg-none') studio_sgNoSong();
    else if (act === 'studio-sg-play') studio_sgPlay();
    else if (act === 'studio-sg-mark') studio_sgMark();
    else if (act === 'studio-sg-fromkills') studio_sgFromKills();
    else if (act === 'studio-sg-marknudge') studio_sgNudgeMark(b.getAttribute('data-d'));
    else if (act === 'studio-sg-markplay') studio_sgHearMark();
    else if (act === 'studio-sg-markdrop') studio_sgDropMark();
    else if (act === 'studio-sg-unmark') studio_sgUnmark();
    else if (act === 'studio-sg-clearmarks') studio_sgClearMarks();
    else if (act === 'studio-sg-nudge') studio_sgNudge(b.getAttribute('data-what'), b.getAttribute('data-d'));
    else if (act === 'studio-sg-snapbar') studio_sgSnapBar();
    else if (act === 'studio-sg-atdrop') studio_sgAtDrop();
    else if (act === 'studio-sg-fit') studio_sgFit();
  });
  document.addEventListener('change', studio_inspectorInput);
  document.addEventListener('change', studio_camInput);
  document.addEventListener('input', studio_camInput);
  document.addEventListener('input', e => { if (e.target && e.target.id === 'studio-gd-name') studio.gd.name = e.target.value; });
  document.addEventListener('input', studio_gdFind);
  document.addEventListener('change', studio_gdViewChange);
  /* A thumbnail that cannot be read is said once, as an empty frame -- never retried, and
     never a broken-image icon in the middle of a card (error does not bubble: caught going down). */
  document.addEventListener('error', e => {
    const t = e.target;
    if (t && t.classList && t.classList.contains('gd-thumbimg')) t.parentNode.classList.add('is-missing');
  }, true);
  const pvv = studio_el('studio-preview-video');
  if (pvv) pvv.addEventListener('timeupdate', () => {
    const h = studio_el('studio-preview-head'), c = studio.clipIndex[(studio.gd.pv || {}).id] || null;
    const dur = c ? Number(c.duration) : (isFinite(pvv.duration) ? pvv.duration : 0);
    if (h && dur > 0) h.style.left = Math.min(100, pvv.currentTime / dur * 100).toFixed(2) + '%';
  });
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
  /* the build clip a Build and drop reel builds on, chosen on the Make page's Footage */
  const mkb = studio_el('studio-mk-build');
  if (mkb) mkb.addEventListener('change', () => { studio.buildClip = mkb.value; studio_mkChip(); });
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
    if (sc) sc.addEventListener('click', e => { if (e.target === sc) { if (id === 'studio-preview-scrim') studio_previewClose(); else studio_closeModals(); } });
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
      /* a clip played from the guide: Escape puts the clip away, not the guide under it */
      if (studio.gd.pv && !studio_el('studio-preview-scrim').classList.contains('hide')) { studio_previewClose(); return; }
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
    /* Undo covers the song's timing too: every change there is an edit of the reel. */
    if (song && (e.ctrlKey || e.metaKey) && (e.key || '').toLowerCase() === 'z') {
      e.preventDefault();
      if (e.shiftKey) studio_redo(); else studio_undo();
      return;
    }
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
    studio_tmKillList(sg).forEach(k => {
      if (k.t >= v.t0 && k.t <= v.t1) x.fillRect(X(k.t) - 1, pad, 2, H - pad);
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

/* ===== THE SONG TAB: the reel's own draft =====================================================

   studio.sg is the timing draft of the reel open on the timeline, in the shape every surface's draft
   has (see THE SONG'S TIMING, above). It is not a copy that can drift: it is READ from the project
   on every draw (studio_sgSync) and every change is WRITTEN back as one edit of the project
   (studio_sgCommit), which is what makes it undoable, what the server checks before a render, and
   what survives leaving the tab. What the plan has not caught up with goes in the project's `draft`
   (clips/editflow.py): the shots are not touched until the player says how. */

/* Each song's analysis, by path: the reel's song and any it is being moved to. */
studio.shapes = {};

async function studio_sgShape(song) {
  if (!song) return null;
  if (studio.shapes[song]) return studio.shapes[song];
  const got = await API.post('/api/reel/song', {song: song}).catch(() => null);
  if (!got || !got.ok) return null;
  studio.shapes[song] = got.song;
  const sg = studio.sg;
  if (sg.song === song && !sg.shape) { sg.shape = got.song; studio_sgReset(); }
  return got.song;
}

/* Where the plan put the kills, in song seconds, and the shot each belongs to: the marks it was cut to,
   or -- for a reel cut to none -- where its kills land now, which is the same thing to edit. */
function studio_sgPlanMarks() {
  const p = studio.project, d = studio.derived;
  if (!p) return {marks: [], names: []};
  const names = (p.shots || []).map(s => (s.caption || s.name || '').replace(/\.mp4$/i, ''));
  if ((p.song_marks || []).length) return {marks: p.song_marks.slice().sort((a, b) => a - b), names: names};
  const off = p.song_offset || 0;
  return {marks: ((d && d.shots) || []).map(r => Math.round((off + r.kill_reel) * 1000) / 1000).sort((a, b) => a - b), names: names};
}

/* THE DRAFT, READ FROM THE PROJECT. Not while a gesture is in flight: a drag owns the range until it
   lets go. */
function studio_sgSync() {
  const p = studio.project, d = studio.derived, sg = studio.sg;
  if (!p || sg.drag || sg.markDrag) return;
  const dr = p.draft || {};
  const song = dr.song !== undefined ? dr.song : (p.song || '');
  if (song !== sg.song) {
    sg.song = song; sg.sel = {};
    sg.shape = song ? (studio.shapes[song] || null) : null;
    if (song && !sg.shape) studio_sgShape(song);
  }
  const len = (d && d.length) || 30;
  sg.start = dr.start !== undefined ? dr.start : (p.song_offset || 0);
  sg.end = dr.end !== undefined && dr.end > sg.start ? dr.end : (p.part_end > sg.start ? p.part_end : sg.start + len);
  if (sg.shape) sg.end = Math.min(sg.end, sg.shape.seconds);
  const anchors = p.anchors || [];
  const mine = t => anchors.some(a => Math.abs(a - t) < 0.002);
  const plan = studio_sgPlanMarks();
  sg.planned = {marks: plan.marks, names: plan.names, hand: plan.marks.map(mine)};
  if (dr.marks) { sg.hand = dr.marks.map((t, i) => ({id: 'm' + i, t: t, auto: !mine(t), name: ''})); sg.edited = true; }
  else { sg.hand = []; sg.edited = false; }
  const drops = dr.drops !== undefined ? dr.drops : (Array.isArray(p.hand_drops) ? p.hand_drops : null);
  sg.drops = drops ? drops.map((t, i) => ({id: 'ud' + i, t: t, auto: false})) : null;
  sg.sel = sg.sel || {};
}

/* THE DRAFT, WRITTEN TO THE PROJECT: only what differs from the plan goes in `draft` -- the part put
   back where it was is no draft, which is how "if it did not change, do nothing" holds. Every mark the
   player placed or moved is one of theirs (`anchors`), and stays one through any plan. */
function studio_tmWriteReel(p, T) {
  const r4 = x => Math.round(x * 10000) / 10000;
  const same = (a, b) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) < 5e-4);
  const d = {};
  if ((T.song || '') !== (p.song || '')) d.song = T.song || '';
  const s0 = p.song_offset || 0, e0 = p.part_end || 0;
  if (d.song !== undefined || Math.abs(T.start - s0) > 5e-4 || Math.abs(T.end - e0) > 5e-4) { d.start = r4(T.start); d.end = r4(T.end); }
  if (T.edited) {
    const times = T.hand.map(k => r4(k.t)).sort((a, b) => a - b);
    if (!same(times, (p.song_marks || []).slice().sort((a, b) => a - b))) d.marks = times;
    const kept = (p.anchors || []).filter(a => T.hand.some(k => !k.auto && Math.abs(k.t - a) < 0.002));
    const mine = T.hand.filter(k => !k.auto).map(k => r4(k.t));
    p.anchors = Array.from(new Set(kept.concat(mine))).sort((a, b) => a - b);
    if (!p.anchors.length) delete p.anchors;
  } else if (T.cleared) {
    delete p.anchors;
  }
  const planned = Array.isArray(p.hand_drops) ? p.hand_drops.slice().sort((a, b) => a - b) : null;
  const want = T.drops ? T.drops.map(x => r4(x.t)).sort((a, b) => a - b) : null;
  if (!(want === null ? planned === null : (planned !== null && same(want, planned)))) d.drops = want;
  if (Object.keys(d).length) p.draft = d; else delete p.draft;
}

/* ONE EDIT OF THE REEL, OR NONE. A change that writes the same draft as before is no change: no undo
   step, no stale reel, no line in what has not been rendered. */
function studio_sgCommit(label) {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  const probe = JSON.parse(JSON.stringify(p));
  studio_tmWriteReel(probe, sg);
  const key = q => JSON.stringify([q.draft || null, q.anchors || []]);
  sg.cleared = false;
  if (key(probe) === key(p)) { studio_sgSync(); studio_sgDraw(); return; }
  /* Whatever was being planned for the draft before this is about a draft that is gone. */
  studio_flowForget();
  studio_change(q => studio_tmWriteReel(q, sg), label || 'The song’s timing');
}

function studio_sgOpen() {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  studio_sgSync();
  studio_sgSongs();
  studio_svLoad(sg.song || '');
  studio_sgReset();
}

function studio_sgReset() {
  const sg = studio.sg, sh = sg.shape;
  studio_show('studio-sg-body', !!sh);
  studio_el('studio-sg-name').textContent = sg.song ? sg.song.split(/[\\/]/).pop() : 'No song';
  studio_el('studio-sg-facts').textContent = sh
    ? Math.round(sh.bpm) + ' BPM · ' + studio_dur(sh.seconds) + (sh.drop ? ' · drop at ' + studio_secs(sh.drop) : '') +
      (sh.drums_in ? ' · drums in at ' + studio_secs(sh.drums_in) : '')
    : sg.song ? 'Finding the beat…' : 'Choose a song to cut the reel to. Without one the clips keep their own sound on a 120 BPM grid.';
  if (!sh) { studio_flowDraw(); return; }
  studio_el('studio-sg-atdrop').disabled = !studio_tmMainDrop(studio_tmView('song'));
  const a = studio_el('studio-sg-audio');
  if (a.getAttribute('data-song') !== sg.song) { a.src = studio_media('/api/reel/audio', sg.song); a.setAttribute('data-song', sg.song); }
  studio_sgDraw();
}

function studio_sgBeat() {
  const sh = studio.sg.shape;
  return sh ? sh.beat || (60 / sh.bpm) : 0.5;
}

function studio_sgNearestBeat(t) { return studio_nearestBeat(studio.sg.shape, t); }

/* A PART MOVED BY A BUTTON, as by a drag: a change only if it is one. */
function studio_sgPart(was, label) {
  const sg = studio.sg;
  if (Math.abs(was.start - sg.start) < 5e-4 && Math.abs(was.end - sg.end) < 5e-4) { studio_sgDraw(); return; }
  studio_sgCommit(label || 'The part of the song');
}

/* THE PART MOVES; THE MARKS DO NOT. A mark is a moment of the song -- the snare a kill lands on -- and
   it stays at that second whatever the part does. It used to be carried along with a moved part, a
   fixed distance from its start, which put it off every beat of the new section and made the reel
   look re-timed when nothing had been re-timed. */
function studio_sgMovePart(start) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const len = sg.end - sg.start;
  sg.start = Math.max(0, Math.min(sh.seconds - Math.min(len, sh.seconds), start));
  sg.end = Math.min(sh.seconds, sg.start + len);
}

function studio_sgNudge(what, how) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const beat = studio_sgBeat(), was = {start: sg.start, end: sg.end};
  const step = {bar: 4 * beat, '-bar': -4 * beat, beat: beat, '-beat': -beat, ms: 0.01, '-ms': -0.01}[how] || 0;
  if (what === 'start') studio_sgMovePart(sg.start + step);
  else sg.end = Math.max(sg.start + beat, Math.min(sh.seconds, sg.end + step));
  studio_sgPart(was);
}

function studio_sgSnapBar() {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.beats || !sh.beats.length) return;
  const bars = sh.beats.filter((b, i) => (i % 4) === (sh.downbeat_pos || 0));
  let best = sg.start, d = 1e9;
  bars.forEach(b => { const x = Math.abs(b - sg.start); if (x < d) { d = x; best = b; } });
  const was = {start: sg.start, end: sg.end};
  studio_sgMovePart(best);
  studio_sgPart(was);
}

function studio_sgAtDrop() {
  const sg = studio.sg, sh = sg.shape, drop = studio_tmMainDrop(studio_tmView('song'));
  if (!sh || drop == null) return;
  const len = sg.end - sg.start, was = {start: sg.start, end: sg.end};
  const lead = Math.min(8 * 4 * studio_sgBeat(), drop, Math.max(4 * studio_sgBeat(), len / 3));
  studio_sgMovePart(Math.max(0, studio_sgNearestBeat(drop - lead)));
  studio_sgPart(was);
}

function studio_sgFit() {
  const sg = studio.sg, sh = sg.shape, d = studio.derived;
  if (!sh || !d) return;
  const was = {start: sg.start, end: sg.end};
  sg.end = Math.min(sh.seconds, sg.start + d.length);
  studio_sgPart(was);
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

/* "WHERE THE KILLS ARE NOW": every kill, where the reel puts it, becomes one of the player's own marks
   -- locked, so no plan or re-time moves it -- and can then be moved rather than retapped. */
function studio_sgFromKills() {
  const sg = studio.sg, got = studio_sgPlanMarks().marks;
  const off = (studio.project && studio.project.song_offset) || 0, d = studio.derived;
  const now = ((d && d.shots) || []).map(r => Math.round((off + r.kill_reel) * 1000) / 1000);
  const at = (now.length ? now : got).slice().sort((a, b) => a - b).filter((t, i, a) => i === 0 || t - a[i - 1] > 0.03);
  if (!at.length) { toast('This reel has no kills to mark yet.'); return; }
  const snap = studio_el('studio-sg-snap').checked;
  sg.hand = at.map((t, i) => ({id: 'k' + i, t: snap ? studio_sgNearestBeat(t) : t, auto: false, name: ''}));
  sg.edited = true; sg.sel = {};
  studio_sgCommit('“Where the kills are now”, kept as your marks');
  toast(at.length + ' marks from the reel, kept as yours. Move any of them, then re-time.');
}

/* One mark chosen, by its chip: the nudges and Hear it act on it. */
function studio_sgSelect(id) {
  const sg = studio.sg;
  sg.sel = sg.sel && sg.sel[id] && Object.keys(sg.sel).length === 1 ? {} : {[id]: true};
  studio_sgDraw();
}

function studio_sgPicked() {
  const sg = studio.sg, ids = Object.keys(sg.sel || {}).filter(id => !studio_mkIsDrop(id));
  return ids.length === 1 ? studio_tmKillList(sg).find(k => k.id === ids[0]) || null : null;
}

/* Moving a mark keeps the list in order: shot N's kill lands on mark N, and the list is sorted after
   every move, so a mark nudged past its neighbour swaps numbers with it rather than swapping shots. */
function studio_sgNudgeMark(how) {
  const k = studio_sgPicked();
  if (!k) return;
  const beat = studio_sgBeat();
  const d = (how === 'beat' ? beat : how === '-beat' ? -beat : how === 'half' ? beat / 2 : -beat / 2);
  studio_tmNudgeMark(studio_tmView('song'), k.id, d);
}

/* A mark is a moment in the music, so the way to judge one is to hear it: this plays the bar it sits
   in rather than asking the ear to remember. */
function studio_sgHearMark() {
  const k = studio_sgPicked(), a = studio_el('studio-sg-audio');
  if (!k || !a) return;
  a.currentTime = Math.max(0, k.t - studio_sgBeat() * 2);
  a.play();
}

function studio_sgDropMark() {
  const ids = Object.keys(studio.sg.sel || {});
  if (ids.length) studio_tmDelIds(studio_tmView('song'), ids);
}

function studio_sgMark() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape) return;
  studio_tmAddMark(studio_tmView('song'), a.currentTime || sg.start);
}

/* The last mark the player placed, taken back. */
function studio_sgUnmark() {
  const sg = studio.sg;
  const mine = studio_tmKillList(sg).filter(k => k.hand);
  if (!mine.length) { toast('There is no mark of yours to take back.', 'warn'); return; }
  const last = sg.edited ? sg.hand.filter(k => !k.auto).reduce((b, k) => (String(k.id) > String(b.id) ? k : b)) : null;
  if (last) studio_tmDelIds(studio_tmView('song'), [last.id]);
}

function studio_sgClearMarks() {
  const sg = studio.sg;
  sg.cleared = true;
  studio_tmClearMarks(studio_tmView('song'));
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
    studio_tmKillList(sg).forEach((m, i) => {
      if (Math.abs(a.currentTime - m.t) < 0.05 && !sg.ticked[i]) { sg.ticked[i] = 1; studio_sgClick(); }
    });
  }
  studio_el('studio-sg-clock').textContent = studio_secs(a.currentTime || 0);
  studio_sgDrawWaves();
  if (!a.paused) requestAnimationFrame(studio_sgTick);
}

function studio_sgDraw() {
  const sg = studio.sg, sh = sg.shape, d = studio.derived, p = studio.project;
  studio_flowDraw();
  if (!sh) return;
  studio_el('studio-sg-start').textContent = studio_secs(sg.start);
  studio_el('studio-sg-end').textContent = studio_secs(sg.end);
  studio_el('studio-sg-range').textContent = 'Using ' + studio_secs(sg.start) + ' → ' + studio_secs(sg.end) +
    ' (' + studio_dur(sg.end - sg.start) + ')';
  const len = d ? d.length : 0, part = sg.end - sg.start;
  studio_el('studio-sg-fitnote').textContent = len > part + 0.05
    ? 'The timeline is ' + studio_dur(len) + '; the part is ' + studio_dur(part) + '. "Fit the timeline" makes the part as long as the reel.'
    : 'The whole timeline fits in this part.';
  const list = studio_tmKillList(sg), stale = studio_tmStale(studio_tmView('song')).length > 0;
  sg.sel = sg.sel || {};
  studio_el('studio-sg-chips').innerHTML = list.map((m, i) =>
    '<span class="reel-chip' + (sg.sel[m.id] ? ' is-on' : '') + (m.hand ? ' is-hand' : ' is-auto') + (stale && !m.hand ? ' is-ghost' : '') +
    '" data-sgmark="' + esc(m.id) + '" title="' + (m.hand ? 'Yours: never moved for you' : 'AutoStream’s: placed again when the reel is re-timed') +
    '">' + (i + 1) + ' · ' + studio_secs(m.t) + '</span>').join('');
  const picked = studio_sgPicked();
  studio_show('studio-sg-marknudge', !!picked);
  if (picked) {
    studio_el('studio-sg-marknum').textContent = String(list.indexOf(picked) + 1);
    studio_el('studio-sg-marktime').textContent = studio_secs(picked.t);
  }
  studio_el('studio-sg-fromkills').disabled = !((d && d.shots) || []).length;
  const shots = p ? p.shots.length : 0, mine = list.filter(k => k.hand).length;
  studio_el('studio-sg-marksinfo').textContent = list.length
    ? list.length + ' marks for ' + shots + ' shots' + (mine ? ', ' + mine + ' of them yours' : '') +
      (list.length < shots ? ' — the rest keep their spacing after the last mark.' : list.length > shots ? ' — the extra marks are not used.' : '.')
    : 'No marks: the shots keep the lengths they have, starting from here.';
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

/* THE WHOLE SONG, and the part up close. The overview carries the marks too, small, at their song
   seconds -- so after the part has moved, the kills still timed for where it was are seen where they
   are, dashed, beside the part they are about to be placed in again. The part the plan was made on is
   outlined while it differs from the one chosen. */
function studio_sgDrawWaves() {
  studio_svDraw();                      /* the lanes follow the playhead too */
  const sg = studio.sg, sh = sg.shape, p = studio.project;
  if (!sh || !sh.peaks) return;
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#5aa9ff';
  const warn = css.getPropertyValue('--warn').trim() || '#e3b341';
  const ok = css.getPropertyValue('--ok').trim() || '#4fc97a';
  const surface = css.getPropertyValue('--surface').trim() || '#111';
  const a = studio_el('studio-sg-audio');
  const now = a ? a.currentTime || 0 : 0;
  const n = sh.peaks.length;
  const v = studio_tmView('song'), why = studio_tmStale(v);
  const o = studio_sgCanvas('studio-sg-overview', 90);
  if (o) {
    const {ctx, W, H} = o, X = t => t / sh.seconds * W, mid = H / 2;
    ctx.fillStyle = accent;
    for (let x = 0; x < W; x++) {
      const k = Math.min(n - 1, Math.floor(x / W * n));
      const amp = sh.peaks[k] * (mid - 10);
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
    if (p && why.indexOf('part') >= 0 && why.indexOf('song') < 0) {
      /* where the kills are still timed for */
      const s0 = p.song_offset || 0, e0 = p.part_end > s0 ? p.part_end : s0 + ((studio.derived && studio.derived.length) || 0);
      ctx.save(); ctx.setLineDash([4, 3]); ctx.strokeStyle = warn; ctx.lineWidth = 1.5;
      ctx.strokeRect(X(s0) + 0.5, 1.5, Math.max(2, X(e0) - X(s0) - 1), H - 3);
      ctx.restore();
    }
    ctx.fillStyle = warn;
    studio_tmDropList(v).forEach(dd => ctx.fillRect(X(dd.t) - 1, 0, 2, H));
    if (why.indexOf('song') < 0) {
      const ghost = why.indexOf('part') >= 0;
      studio_tmKillList(sg).forEach(k => {
        const x = X(k.t), y = H - 7;
        ctx.save();
        ctx.beginPath(); ctx.moveTo(x, y - 5); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 5); ctx.lineTo(x - 5, y); ctx.closePath();
        if (k.hand) { ctx.fillStyle = accent; ctx.fill(); }
        else {
          if (ghost) { ctx.globalAlpha = 0.6; ctx.setLineDash([2, 2]); }
          ctx.fillStyle = surface; ctx.fill(); ctx.strokeStyle = ok; ctx.lineWidth = 1.25; ctx.stroke();
        }
        ctx.restore();
      });
    }
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(now) - 1, 0, 2, H);
    o.cv.title = 'Drag the highlighted part to move it, or its edges to resize it';
  }
  studio_tmKillsDraw(v);
}

function studio_sgPointer(e) {
  const sg = studio.sg;
  studio_tmPartPointer(e, {T: sg, sh: sg.shape, cv: studio_el('studio-sg-overview'),
    redraw: studio_sgDraw, commit: was => studio_sgPart(was)});
}

/* The part up close: the shared marks canvas (studio_tmKillPointer); a click on the empty song is a seek. */
function studio_sgDetailPointer(e) {
  studio_tmKillPointer(studio_tmView('song'), e, t => {
    const a = studio_el('studio-sg-audio');
    if (a) a.currentTime = Math.max(0, t);
    studio_el('studio-sg-clock').textContent = studio_secs(t);
    studio_sgDrawWaves();
  });
}

async function studio_sgPick() {
  const r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) return;
  await studio_sgUseSong(r.path);
}

/* A SONG FILE AS THE REEL'S SONG -- a change to the draft like any other: the part is placed where the
   drums come in and the reel's timing is stale until the player replans or re-times it. The old song's
   marks were beats of that song, so none is carried over. -> whether it could be read. */
async function studio_sgUseSong(path) {
  studio_el('studio-sg-facts').textContent = 'Finding the beat in ' + path.split(/[\\/]/).pop() + '…';
  const got = await API.post('/api/reel/song', {song: path});
  if (!got || !got.ok) { studio_el('studio-sg-facts').textContent = (got && got.error) || 'Could not read that song.'; return false; }
  const sg = studio.sg, sh = got.song, len = (studio.derived && studio.derived.length) || 30;
  studio.shapes[path] = sh;
  if (!studio.project) {
    sg.song = path; sg.shape = sh;
    studio_sgSongs(); studio_sgReset();
    return true;
  }
  sg.song = path; sg.shape = sh; sg.hand = []; sg.edited = false; sg.sel = {}; sg.drops = null;
  const from = sh.drums_in || (sh.beats && sh.beats[0]) || 0;
  sg.start = studio_nearestBeat(sh, Math.max(0, Math.min(from, sh.seconds - len)));
  sg.end = Math.min(sh.seconds, sg.start + len);
  studio_sgCommit('The song: ' + path.split(/[\\/]/).pop());
  studio_sgSongs();
  studio_svLoad(path);
  studio_sgReset();
  return true;
}

/* NO SONG: the reel's music taken off, at once. One explicit button, and one step of undo. */
async function studio_sgNoSong() {
  const p = studio.project;
  if (!p) return;
  studio_el('studio-sg-msg').textContent = 'Taking the song off…';
  const snapshot = JSON.stringify(p);
  const gen = ++studio.gen;
  const r = await API.post('/api/studio/song', {project: p, song: ''});
  if (gen !== studio.gen) return;
  studio_el('studio-sg-msg').textContent = '';
  if (!r || !r.ok) { toast((r && r.error) || 'Could not take the song off.', 'warn'); return; }
  studio_pushUndo(snapshot, 'The song taken off');
  r.project.output = p.output;
  studio_setProject(r.project, r.derived, r.notes, r.song);
  studio_touched('The song taken off', -1, studio_diff(JSON.parse(snapshot), r.project));
  studio.sg.song = ''; studio.sg.shape = null;
  toast('The reel has no song now.', 'ok');
  studio_tab('timeline');
}

function studio_sgWire() {
  const ov = studio_el('studio-sg-overview'), de = studio_el('studio-sg-detail');
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(ev => {
    if (ov) ov.addEventListener(ev, studio_sgPointer);
  });
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'dblclick'].forEach(ev => {
    if (de) de.addEventListener(ev, studio_sgDetailPointer);
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
    studio_sgSelect(c.getAttribute('data-sgmark'));
  });
  window.addEventListener('resize', () => { if (shell_page === 'studio') studio_sgDrawWaves(); });
}

/* =====================================================================
   THE GUIDED MAKER: one question per screen.
   The Make page asks everything at once -- eight styles, six orders, three lengths, four dials
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
/* Montage since v1.79.15: its third review, 7.2/10 on its own planner (4.2 on the general one); the one blocker
   named, capture overlays in the footage, is the cleanup the player set aside. */
/* Hype (7.6/10) and Velocity (7.2/10) after their pace-and-signature review: both run on the general
   planner, which is why "Pick the style for me" no longer means "a style with a planner of its own" --
   it skips only a verdict that says its style fell back to another planner (`fallback`), and these two
   never do: the general planner is theirs. */
const GD_BEST = ['drop', 'fasthead', 'montage', 'hype', 'velocity'];
/* THE GUIDE OWNS ITS SPEC. Everything a guided reel is made from is here or in the song: the style,
   the clips, the shape, the lyrics, the name. Nothing is read from the Make page -- Perfect fit left
   there, Headshots only ticked there, an intro, kills or drops marked there, a reel being rebuilt
   there all used to reach a guided plan unseen, and some reached the verdict but not the plan. One
   function, studio_gdBody, turns this into the request, and the verdict and the plan both send it.
   `run` is the plan in flight: closing or going Back bumps it, and a plan that returns to a newer
   run is dropped. `held` is what the chip says when a reel was not made (a render running, a plan
   refused), until the next answer. `drops` are the song's drops as the player marked them on the Song
   step, null while they are AutoStream's: part of the spec, so the verdict and the plan both carry
   them; a drop belongs to its song, and a new song or a new reel starts from null again. */
studio.gd = {step: 0, style: '', auto: false, autoWhy: null, setup: '', quick: [], fmt: 'vertical', fit: 'near', lyrics: 'off', name: '',
             /* ONE DRAFT: the guide's drops are the Make page's (studio.mk.drops), so a drop marked on
                either is the same drop on both, and All settings has nothing to copy. */
             get drops() { return studio.mk.drops; }, set drops(v) { studio.mk.drops = v; },
             parts: null, head: 0, snap: false, dropDrag: null,
             verdict: null, asked: 0, autoAsked: 0, busy: false, run: 0, held: null, timer: null,
             /* the Clips step's browsers (studio_gdView), the clip playing over the guide, the one being trimmed */
             views: null, pv: null, editing: null};

/* A STYLE KEY KEPT FROM BEFORE A STYLE WAS RETIRED means the style that replaced it -- the server's
   own map (studio.RETIRED_STYLES), so the guide's memory and a render's history agree with what the
   reel now opens as. */
function studio_styleNow(k) {
  const gone = (studio.catalog && studio.catalog.retired_styles) || {};
  return Object.prototype.hasOwnProperty.call(gone, k) ? gone[k] : k;
}

/* WHAT WAS CHOSEN LAST TIME, remembered as intent -- the style, the shape, the framing -- and not as
   results: the song and the clips are checked again against what exists now, and the chip is asked
   again, so a remembered answer never skips the check. */
const GD_KEY = 'autostream.guide';
function studio_gdRemember() {
  const gd = studio.gd;
  try { localStorage.setItem(GD_KEY, JSON.stringify({style: gd.style, fmt: gd.fmt, fit: gd.fit, lyrics: gd.lyrics, song: studio.song || '',
                                                      setup: gd.setup, quick: gd.quick})); } catch (e) { /* private window: nothing remembered */ }
}
function studio_gdRecall() {
  let m = null;
  try { m = JSON.parse(localStorage.getItem(GD_KEY) || 'null'); } catch (e) { m = null; }
  if (!m || typeof m !== 'object') return false;
  const gd = studio.gd, have = id => !!studio.clipIndex[id];
  const style = studio_styleNow(m.style);
  if (style && studio.catalog.styles.some(s => s.key === style)) gd.style = style;
  if (m.fmt === 'vertical' || m.fmt === 'landscape') gd.fmt = m.fmt;
  if (['fit', 'near', 'zoom'].includes(m.fit)) gd.fit = m.fit;
  if (typeof m.lyrics === 'string' && (m.lyrics === 'off' || studio_gdLyricLooks().some(l => l.key === m.lyrics))) gd.lyrics = m.lyrics;
  gd.setup = have(m.setup) ? m.setup : '';
  gd.quick = (Array.isArray(m.quick) ? m.quick : []).filter(have);
  return !!gd.style;
}

function studio_gdStyle(key) {
  const cat = studio.catalog, k = key === undefined ? studio.gd.style : key;
  return cat ? cat.styles.find(s => s.key === k) : null;
}

/* THE GAME OF THE REEL: the one most of the chosen clips are from -- clips picked on the Clips tab
   decide it -- else the one the player has most favourites in. */
function studio_gdGame() {
  const gd = studio.gd, by = {};
  Object.values(studio.clipIndex || {}).forEach(c => {
    if (!(c.kills || []).length) return;
    const g = c.game || '';
    by[g] = by[g] || {n: 0, fav: 0, picked: 0}; by[g].n++; if (c.fav) by[g].fav++;
  });
  [gd.setup].concat(gd.quick).forEach(id => { const c = studio.clipIndex[id]; if (c && by[c.game || '']) by[c.game || ''].picked++; });
  const games = Object.keys(by).sort((a, b) => (by[b].picked - by[a].picked) || (by[b].fav - by[a].fav) || (by[b].n - by[a].n));
  return games.length ? games[0] : '';
}
/* every clip the library holds of that game */
function studio_gdClips() {
  const g = studio_gdGame();
  return Object.values(studio.clipIndex || {}).filter(c => (c.kills || []).length && (c.game || '') === g);
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

/* WHY A CHOSEN CLIP IS NOT IN THIS STYLE'S REEL, or '' when it is. Asked again on every change of
   style: the selection is the player's and stays in the draft, but a clip the style cannot use is
   left out of the counts, the targets, the verdict and the plan -- and shown, with this reason --
   rather than kept out of sight and counted. Montage's seven body kills went on counting under
   Fast-paced headshot, and a clip of another game passed from the Clips tab could not be removed. */
function studio_gdWhyNot(c, style) {
  if (!(c.kills || []).length) return 'no kill was read in it';
  const g = studio_gdGame();
  if ((c.game || '') !== g) return 'another game (' + (c.game || 'unknown') + '): this reel is ' + (g || 'one game');
  if (style === 'fasthead' && !studio_gdHs(c)) return 'not a headshot: this style is headshots only';
  return '';
}
/* A clip deleted while the guide is open leaves the draft: there is nothing left to show or send. */
function studio_gdPrune() {
  const gd = studio.gd, have = id => !!studio.clipIndex[id];
  if (gd.setup && !have(gd.setup)) gd.setup = '';
  gd.quick = gd.quick.filter(have);
}
/* What the player has chosen, usable or not. The build slot is Build and drop's alone; in any other
   style a build clip chosen earlier is one of the clips (studio_gdAct moves it there). */
function studio_gdChosen(d) {
  d = d || studio.gd;
  const out = d.style === 'drop' && d.setup ? [d.setup] : [];
  d.quick.forEach(id => { if (out.indexOf(id) < 0) out.push(id); });
  return out;
}
/* The clips the reel is made of: chosen, and usable by the style. */
function studio_gdIds(d) {
  d = d || studio.gd;
  return studio_gdChosen(d).filter(id => studio.clipIndex[id] && !studio_gdWhyNot(studio.clipIndex[id], d.style));
}
function studio_gdLeftOut(d) {
  d = d || studio.gd;
  return studio_gdChosen(d).map(id => studio.clipIndex[id]).filter(Boolean)
    .map(c => ({c: c, why: studio_gdWhyNot(c, d.style)})).filter(x => x.why);
}

/* THE CLIPS EACH STYLE CAN USE. Build and drop splits them into a build and quick kills.
   Fast-paced headshot is headshots only (clips/fasthead.py): a clip with none is no use to it,
   and Pick for me used to fill its slots with body kills the plan then left out. Any other style
   takes every clip -- the build's clutches included, which only Build and drop sets apart. */
function studio_gdPools(style, setup) {
  style = style === undefined ? studio.gd.style : style;
  setup = setup === undefined ? studio.gd.setup : setup;
  const all = studio_gdClips();
  const setups = all.filter(studio_gdIsSetup).sort((a, b) => studio_gdSetupScore(b) - studio_gdSetupScore(a));
  if (style === 'fasthead') {
    const quick = all.filter(c => studio_gdHs(c) > 0)
      .sort((a, b) => (studio_gdHsDouble(b) - studio_gdHsDouble(a)) || (studio_gdQuickScore(b) - studio_gdQuickScore(a)));
    return {setups: [], quick: quick};
  }
  const quick = all.filter(c => style !== 'drop' || (!studio_gdIsSetup(c) && c.id !== setup))
    .sort((a, b) => studio_gdQuickScore(b) - studio_gdQuickScore(a));
  return {setups: setups, quick: quick};
}
/* two headshots of one clip within 2.5 s: a real double, the only finale Fast-paced headshot takes */
function studio_gdHsDouble(c) {
  const ks = (c.kills || []).map((k, i) => [Number(k), (c.hs || [])[i] === true]).sort((a, b) => a[0] - b[0]);
  return ks.some((k, i) => i > 0 && k[1] && ks[i - 1][1] && k[0] - ks[i - 1][0] >= 0.25 && k[0] - ks[i - 1][0] <= 2.5) ? 1 : 0;
}

/* THE DROP AND THE PART THE GUIDE PLANS ON: the guide's drops -- the song's own, or the player's --
   for the guide's own shape and style. */
function studio_gdMainDrop(d) { return studio_dropsMain((d || studio.gd).drops, studio.songShape); }
function studio_gdPart(d) {
  d = d || studio.gd;
  const sh = studio.songShape, mk = studio.mk;
  if (!studio.song || !sh || !sh.seconds) return null;
  /* the part the player chose on All settings is the draft's, and the guide's too */
  if (mk.touched && mk.mode === 'part' && mk.end > mk.start) return [mk.start, mk.end];
  return studio_partFor(sh, d.fmt, d.style === 'drop' ? studio_gdMainDrop(d) : null);
}
function studio_gdKillsIn(ids) {
  return ids.reduce((n, id) => n + (((studio.clipIndex[id] || {}).kills || []).length || 0), 0);
}

/* ONE COUNT, AND IT IS THE PLAN'S. How many clips a reel needs was estimated three ways -- the
   counter here (a quick kill every 0.52 s, a two-kill clip as two), the chip (missing seconds over a
   kill's length) and "Add the best" (the counter's number) -- and on JUST A BOY they disagreed: "50 of
   41" chosen, "about 13 more", and a button that added nothing (2026-10-24). Now the page never
   counts: what the plan made and what it is short come back with the verdict (clips/feasible.py),
   and adding is done by the server, which plans again and keeps only the clips the plan plays.

   WHAT PICK FOR ME OFFERS THE PLAN, for any draft: the build clip -- the player's, whatever the
   scores say, unless it cannot be in this reel at all ("Pick the best" used to swap the ACE they had
   chosen for the clip that scored highest) -- and every other clip the style can use, best first. */
function studio_gdOffer(d) {
  let setup = d.setup;
  if (d.style === 'drop') {
    const own = setup && studio.clipIndex[setup];
    if (!own || studio_gdWhyNot(own, 'drop')) {
      const best = studio_gdPools('drop', '').setups[0];
      setup = best ? best.id : '';
    }
  }
  const quick = studio_gdPools(d.style, setup).quick.filter(c => !(d.style === 'drop' && c.id === setup)).map(c => c.id);
  return {setup: setup, quick: quick};
}
/* PICK FOR ME (`top` false: from nothing) AND "ADD N MORE" (`top`: every clip chosen stays). The
   server adds the next clips the verdict asks for, plans again, keeps only those the plan plays, and
   repeats until it is full -- or says why it cannot be. -> {setup, quick, verdict} for the draft, or
   null when it could not be asked. */
async function studio_gdFill(d, top) {
  const o = studio_gdOffer(d);
  const draft = Object.assign({}, d, {setup: o.setup, quick: top ? d.quick.slice() : []});
  const body = studio_gdBody(draft), byPath = {};
  body.candidates = o.quick.filter(id => draft.quick.indexOf(id) < 0).map(id => {
    const p = studio.clipIndex[id].path;
    byPath[p] = id;
    return p;
  });
  const got = await API.post('/api/studio/fill', body).catch(() => null);
  if (!got || !got.ok) return null;
  draft.quick = draft.quick.concat((got.added || []).map(p => byPath[p]).filter(Boolean));
  const v = Object.assign({}, got.verdict, {length: got.length});
  if (got.why) v.why = got.why;
  return {setup: draft.setup, quick: draft.quick, verdict: v, judged: studio_gdBody(draft), added: (got.added || []).length};
}
async function studio_gdPickAll(top) {
  const gd = studio.gd, ticket = gd.fillAsked = (gd.fillAsked || 0) + 1, was = JSON.stringify([gd.style, gd.setup, gd.quick]);
  clearTimeout(gd.timer);
  gd.filling = true;
  gd.verdict = {level: 'ok', text: top ? 'Adding the clips the plan is short of…' : 'Picking the clips the plan needs…'};
  studio_gdDraw();
  const got = await studio_gdFill(gd, !!top);
  if (ticket !== gd.fillAsked) return;
  gd.filling = false;
  /* a clip chosen or a style changed while it planned: the answer is to another question */
  if (JSON.stringify([gd.style, gd.setup, gd.quick]) !== was) { gd.verdict = null; return studio_gdDraw(); }
  if (!got) { gd.verdict = {level: 'warn', text: 'Could not check this against your clips just now.'}; return studio_gdDraw(); }
  gd.setup = got.setup; gd.quick = got.quick;
  gd.verdict = got.verdict; gd.judged = got.judged;
  studio_gdDraw();
}

/* THE ONE REQUEST. Built from the guide's spec and nothing else, for the verdict and the plan alike,
   so what the chip judged is what gets planned: the same clips, the same part (from the guide's own
   shape), the same build clip, and every way of ordering and dialling set to the style's own --
   `arrange` said outright, so a Perfect fit chosen on the Make page cannot take over a Build and
   drop. `d` is a draft of the spec (Pick the style for me judges three); the guide's own when absent. */
function studio_gdBody(draft) {
  const d = draft || studio.gd, ids = studio_gdIds(d), part = studio_gdPart(d);
  const body = {
    clips: ids.map(id => studio.clipIndex[id].path), style: d.style, song: studio.song,
    format: d.fmt, vfit: d.fmt === 'vertical' ? d.fit : 'zoom',
    name: String(d.name || '').trim() || studio_gdDefaultName(d),
    template: null,
    shaping: {length: 1, pace: 1, effects: 1, flash: 1, arrange: 'build', pins: {}, shuffle_seed: 0,
              hs_only: false, fill: '', keep_all: false}
  };
  if (d.style === 'drop' && d.setup && ids.indexOf(d.setup) >= 0) body.shaping.build_clip = studio.clipIndex[d.setup].path;
  if (part) {
    body.part_start = part[0];
    body.part_end = part[1];
    /* drawn by the guide, never moved: Build and drop takes it as a length -- unless the player chose it */
    if (!studio.mk.touched) body.shaping.part_auto = true;
  }
  /* kill marks the player placed on All settings are this draft's too */
  if (studio.song && studio.mk.edited && studio.mk.hand.length) body.marks = studio.mk.hand.map(k => Math.round(k.t * 1000) / 1000);
  /* the drops as the player marked them on the Song step; none sent while they are the song's own */
  if (studio.song && d.drops) body.drops = studio_dropsSent(d.drops);
  if (d.lyrics && d.lyrics !== 'off') body.keep = {lyrics: {look: d.lyrics}};
  return body;
}

/* THE SPEC, HANDED TO THE MAKE PAGE: what All settings opens on and what a guided reel leaves there.
   Every setting the guide does not ask goes back to the style's own, so the page shows the reel the
   guide judged and its Build sends the same request (studio_planBody == studio_gdBody). A new reel,
   never a rebuild: "Add clips" to another reel is not carried into it. */
function studio_gdHandOff(body) {
  const gd = studio.gd, b = body || studio_gdBody(), ids = studio_gdIds(), mk = studio.mk;
  if (gd.style) studio.style = gd.style;
  studio.fmt = gd.fmt; studio.vfit = gd.fit;
  studio.selected = ids; studio_syncSelection();
  studio.buildClip = (b.shaping || {}).build_clip || '';
  studio.adding = null; studio.picks = null; studio.order = 'chosen';
  studio.shaping = {length: 1, pace: 1, effects: 1, flash: 1};
  studio.arrange = 'build'; studio.pins = {}; studio.shuffleSeed = 0;
  studio.fill = ''; studio.keepAll = false;
  studio.mkIntro = {path: '', audio: false};
  studio.mkKeep = b.keep ? JSON.parse(JSON.stringify(b.keep)) : null;
  const hs = studio_el('studio-hs-only');
  if (hs) hs.checked = false;
  /* THE TIMING IS ONE DRAFT, NOT HANDED OVER: the part, the marks and the drops are studio.mk already,
     whichever page is showing it -- a part chosen on All settings and a drop marked on the Song step
     are the same draft's. Only an untouched part is drawn again here, from the guide's own choice. */
  mk.sel = {};
  mk.mode = 'part';
  if (!mk.touched && b.part_start != null) { mk.start = b.part_start; mk.end = b.part_end; }
  studio_el('studio-name').value = b.name;
  studio_arrangeDraw();
  studio_shapeDraw();
}

async function studio_gdOpen() {
  if (!studio.songList) {                  /* the songs already downloaded, for step two */
    const r = await API.get('/api/studio/songs').catch(() => null);
    studio.songList = (r && r.ok && r.songs) || [];
  }
  if (!studio.catalog || !Object.keys(studio.clipIndex || {}).length) { toast('The clips are still loading.', 'warn'); return; }
  const gd = studio.gd;
  gd.step = 0; gd.verdict = null; gd.held = null;
  /* A draft seeded from a reel being rebuilt is that reel's; a new reel does not start from it. A new
     reel's own draft is kept across closing and opening the guide, as everything chosen there is. */
  if (studio.mk.of && studio.mk.of !== 'new') studio_tmFresh();
  if (!gd.style && !gd.auto) studio_gdRecall();
  studio_gdPrune();
  studio_gdAudioWire();
  studio_show('studio-preview-scrim', false);
  studio_show('studio-make-scrim', false);
  studio_show('studio-guide-scrim', true);
  studio_makePage(true);
  studio_gdDraw();
}
/* The guide with the clips picked on the Clips tab already in it: the best set-up among them in the
   build slot when the style builds, the rest as its clips. */
async function studio_gdOpenWith(ids) {
  await studio_gdOpen();
  const gd = studio.gd;
  const clips = (ids || []).map(id => studio.clipIndex[id]).filter(Boolean);
  if (!clips.length || studio_el('studio-guide-scrim').classList.contains('hide')) return;
  const setups = clips.filter(studio_gdIsSetup).sort((a, b) => studio_gdSetupScore(b) - studio_gdSetupScore(a));
  gd.setup = gd.style !== 'drop' && gd.style ? '' : (setups[0] ? setups[0].id : '');
  gd.quick = clips.map(c => c.id).filter(id => id !== gd.setup);
  gd.verdict = null;
  studio_gdDraw();
}
/* A plan in flight, let go: its answer is dropped when it comes (studio_build checks buildGen), and
   the guide is usable at once rather than ignoring every click until it does. */
function studio_gdDetach() {
  const gd = studio.gd;
  if (!gd.busy) return;
  gd.run++; studio.buildGen++; gd.busy = false;
}
function studio_gdClose() {
  studio_gdDetach();
  const a = studio_el('studio-gd-audio');
  if (a && !a.paused) a.pause();
  studio_show('studio-guide-scrim', false);
  studio_makePage(false);
}

function studio_gdCanGo(i) {
  const gd = studio.gd;
  if (gd.busy && i !== gd.step) return false;   /* planning: Back or Close lets go of it first */
  if (i <= 0) return true;
  if (!gd.style && !gd.auto) return false;
  if (i >= 2 && !studio.song) return false;
  if (i >= 3 && !studio_gdIds().length) return false;
  return true;
}

function studio_gdDraw() {
  const gd = studio.gd;
  studio_gdPrune();
  studio_el('studio-gd-steps').innerHTML = GD_STEPS.map((n, i) =>
    '<li><button type="button" class="gd-step' + (i === gd.step ? ' is-on' : '') + (i < gd.step ? ' is-done' : '') +
    '" data-act="studio-gd" data-gd="step" data-i="' + i + '"' + (studio_gdCanGo(i) ? '' : ' disabled') +
    ' aria-current="' + (i === gd.step ? 'step' : 'false') + '"><b>Step ' + (i + 1) + '</b><span>' + esc(n) + '</span></button></li>').join('');
  const draw = [studio_gdDrawStyle, studio_gdDrawSong, studio_gdDrawClips, studio_gdDrawLook, studio_gdDrawCheck][gd.step];
  studio_el('studio-gd-body').innerHTML = draw();
  if (gd.step === 1) studio_gdDropWire();
  else { const a = studio_el('studio-gd-audio'); if (a && !a.paused) a.pause(); }
  const back = studio_el('studio-gd-back');
  back.disabled = gd.step === 0;
  back.textContent = gd.busy ? 'Back (stop planning)' : 'Back';
  const next = studio_el('studio-gd-next');
  next.textContent = gd.step === 4 ? (gd.busy ? 'Planning…' : 'Make the reel') : 'Next';
  next.disabled = gd.step < 4 ? !studio_gdCanGo(gd.step + 1) : (gd.busy || !!(gd.verdict && gd.verdict.level === 'bad'));
  /* the name as it is typed, so a redraw keeps it and the request carries it */
  const nm = studio_el('studio-gd-name');
  if (nm) nm.addEventListener('input', () => { gd.name = nm.value; });
  if (gd.busy) return;                     /* the chip is saying what the plan is doing */
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
    '<span class="muted">We try each recommended style on the song and your clips, and choose the one that works best.</span></button>' +
    (gd.auto && studio.song ? studio_gdAutoNote() : '') +
    '<div class="gd-grid gd-grid-best">' + best.map(card).join('') + '</div>' +
    '<details class="gd-more"' + (gd.style && !GD_BEST.includes(gd.style) ? ' open' : '') + '><summary>More styles <span class="muted">(not reviewed yet: they work, but are not at the standard of the ones above)</span></summary>' +
    '<div class="gd-grid">' + rest.map(card).join('') + '</div></details>';
}

/* WHAT PICK THE STYLE FOR ME FOUND, in words: the style it chose and why not the others -- or, when
   none fits, each one's reason and what to do instead, never a dead end. */
function studio_gdAutoNote() {
  const gd = studio.gd, why = gd.autoWhy;
  if (!why) return '<p class="muted">Trying each recommended style on this song and your clips…</p>';
  const others = why.filter(w => w.key !== gd.style);
  const list = others.length ? '<ul class="gd-why">' + others.map(w => '<li><b>' + esc(w.label) + ':</b> ' + esc(w.text) + '</li>').join('') + '</ul>' : '';
  if (gd.style) {
    return '<div class="gd-field"><p class="gd-picked"><b>' + esc((studio_gdStyle() || {label: ''}).label) +
      '</b> suits this song with your clips.' + (others.length ? ' Not the others:' : '') + '</p>' + list + '</div>';
  }
  return '<div class="gd-field"><p class="gd-note">None of the recommended styles works with this song and your clips:</p>' + list +
    '<div class="gd-acts">' + (studio.songShape && studio_gdMainDrop() == null
      ? '<button type="button" class="btn btn-primary btn-sm" data-act="studio-gd" data-gd="fix" data-fix="mark-drop:drop">Mark the drop yourself, for Build and drop</button>' : '') +
    '<button type="button" class="btn btn-primary btn-sm" data-act="studio-gd" data-gd="step" data-i="1">Choose another song</button>' +
    '<button type="button" class="btn btn-sm" data-act="studio-gd" data-gd="more">Show the other styles</button></div></div>';
}

/* Each recommended style, tried on this song with the clips it would take (the player's own, when
   they have chosen some), through the same verdict the chip gives; the best that works is chosen --
   one that works before one that works with a but, in the order of GD_BEST. It used to choose Build
   and drop when the song had a drop and nothing otherwise, so a song with none was a dead end. */
async function studio_gdAutoStyle() {
  const gd = studio.gd, mine = studio_gdChosen(Object.assign({}, gd, {style: ''})).length > 0;
  const ticket = ++gd.autoAsked;
  const keys = GD_BEST.filter(k => studio.catalog.styles.some(s => s.key === k));
  const drafts = keys.map(k => {
    const d = Object.assign({}, gd, {style: k, quick: mine ? gd.quick.slice() : []});
    if (mine && k !== 'drop' && d.setup && d.quick.indexOf(d.setup) < 0) d.quick.unshift(d.setup);
    return d;
  });
  /* nothing chosen yet: each style is judged on the clips the plan itself would pick for it */
  const got = await Promise.all(drafts.map(d => {
    const none = studio_gdNone(d);
    if (none && (mine || !studio_gdOffer(d).quick.length)) return Promise.resolve({ok: true, verdict: none});
    if (!mine) return studio_gdFill(d, false).then(f => f ? (Object.assign(d, {setup: f.setup, quick: f.quick}), {ok: true, verdict: f.verdict}) : null);
    return API.post('/api/studio/feasible', studio_gdBody(d)).catch(() => null);
  }));
  if (ticket !== gd.autoAsked || !gd.auto) return;
  const rank = {ok: 0, warn: 1};
  const tried = drafts.map((d, i) => ({d: d, v: got[i] && got[i].ok ? got[i].verdict : {level: 'bad', text: 'It could not be checked just now.'}}));
  gd.autoWhy = tried.map(x => ({key: x.d.style, label: (studio_gdStyle(x.d.style) || {label: x.d.style}).label, level: x.v.level, text: x.v.text}));
  /* a style that could only be planned the general way is that style in name only: not chosen */
  const fits = tried.filter(x => x.v.level in rank && !x.v.fallback).sort((a, b) => rank[a.v.level] - rank[b.v.level]);
  if (!fits.length) { gd.style = ''; return; }
  const pick = fits[0].d;
  gd.style = pick.style;
  if (!mine) { gd.setup = pick.setup; gd.quick = pick.quick; }
  else if (pick.style !== 'drop') gd.quick = pick.quick;
}

/* THE SONG, SEEN AND MARKED, ON THE SONG STEP. Build and drop on a song whose drop the analysis
   missed was a dead end ("choose another song"); the drops could only be seen and marked on the
   Make page, which the guide does not show. The same machinery as the Make page's drop lane
   (studio_dropsOf and the rest, above), on the guide's own list, `gd.drops`: null while the drops
   are AutoStream's, a list once the player has touched them. The list is part of the guide's spec,
   so the verdict and the plan both carry it (studio_gdBody). */
const GD_LEAD = 4;                         /* "Play into the drop" starts this many seconds before it */
const GD_DROP_H = 150, GD_DROP_LANE = 24, GD_DROP_PARTS = 18;

/* The song's parts and loudness, read once per song for the drawing -- not needed to plan. */
async function studio_gdParts() {
  const gd = studio.gd, song = studio.song;
  if (!song || (gd.parts && gd.parts.song === song)) return;
  gd.parts = {song: song, sections: [], energy: [], hz: 10, loading: true};
  const r = await API.post('/api/studio/songparts', {song: song}).catch(() => null);
  if (!gd.parts || gd.parts.song !== song) return;
  gd.parts = {song: song, sections: (r && r.ok && r.sections) || [], energy: (r && r.ok && r.energy) || [],
              hz: (r && r.hz) || 10, loading: false};
  studio_gdDropDraw();
}

function studio_gdAudio() {
  const a = studio_el('studio-gd-audio');
  if (a && studio.song && a.getAttribute('data-song') !== studio.song) {
    a.pause();
    a.src = studio_media('/api/reel/audio', studio.song);
    a.setAttribute('data-song', studio.song);
  }
  return a;
}
/* where the playhead is: the player's, once it has the song, else where it was last sent */
function studio_gdNow() {
  const a = studio_el('studio-gd-audio');
  return a && a.getAttribute('data-song') === studio.song && a.readyState >= 1 ? (a.currentTime || 0) : (studio.gd.head || 0);
}
function studio_gdSeek(t) {
  const a = studio_gdAudio(), sh = studio.songShape;
  if (!a || !sh) return;
  t = Math.max(0, Math.min(sh.seconds, t));
  if (a.readyState >= 1) a.currentTime = t;
  else a.addEventListener('loadedmetadata', () => { a.currentTime = t; }, {once: true});
  studio.gd.head = t;
  studio_gdDropDraw();
}
function studio_gdPlay(from) {
  const a = studio_gdAudio();
  if (!a) return;
  if (from == null && !a.paused) { a.pause(); return; }
  if (from != null) studio_gdSeek(from);
  a.play().catch(() => toast('The song could not be played.', 'warn'));
}
/* Into a drop: from a few seconds before it, so the build is heard arriving. */
function studio_gdPlayInto(t) { studio_gdPlay(Math.max(0, t - GD_LEAD)); }

/* The guide's drops, as the drawing and the list show them. */
function studio_gdDropList() { return studio_dropsOf(studio.gd.drops, studio.songShape); }
/* A change to the drops is a change to the spec: the part may move and the verdict is asked again. */
function studio_gdDropsChanged() {
  const gd = studio.gd;
  gd.drops.sort((x, y) => x.t - y.t);
  gd.verdict = null;
  studio_gdDraw();
}
function studio_gdAddDrop(t) {
  const gd = studio.gd, sh = studio.songShape;
  if (!sh) return;
  gd.drops = studio_dropsOwned(gd.drops, sh);
  gd.drops.push(studio_dropNew(Math.max(0, Math.min(sh.seconds, t)), 'studio-gd-snap'));
  studio_gdDropsChanged();
}
function studio_gdDelDrop(id) {
  const gd = studio.gd;
  gd.drops = studio_dropsOwned(gd.drops, studio.songShape).filter(d => d.id !== id);
  studio_gdDropsChanged();
}
function studio_gdNudgeDrop(id, by) {
  const gd = studio.gd;
  gd.drops = studio_dropsOwned(gd.drops, studio.songShape);
  const d = gd.drops.find(x => x.id === id);
  if (!d) return;
  d.t = Math.max(0, Math.round((d.t + by) * 1000) / 1000); d.auto = false;
  studio_gdDropsChanged();
}

function studio_gdDropView() {
  const gd = studio.gd, sh = studio.songShape;
  if (!sh) return '';
  const list = studio_gdDropList(), main = studio_gdMainDrop();
  const row = (d, i) => {
    const name = 'drop ' + (i + 1), isMain = main != null && Math.abs(d.t - main) < 1e-3;
    return '<li class="gd-droprow' + (d.hand ? ' is-hand' : '') + '"><span class="mono">D' + (i + 1) + '</span>' +
      '<span class="mono">' + esc(studio_secs(d.t)) + '</span><span class="gd-who">' + (d.hand ? 'yours' : 'AutoStream’s') + '</span>' +
      (isMain ? '<span class="gd-main">main drop</span>' : '<span></span>') +
      '<span class="gd-droptools">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="drop-into" data-t="' + d.t + '" aria-label="Play into ' + name + '">Play into</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="drop-nudge" data-id="' + esc(d.id) + '" data-by="-0.1" aria-label="Move ' + name + ' a tenth of a second earlier">&minus;0.1</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="drop-nudge" data-id="' + esc(d.id) + '" data-by="0.1" aria-label="Move ' + name + ' a tenth of a second later">+0.1</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="drop-del" data-id="' + esc(d.id) + '" aria-label="Remove ' + name + '">Remove</button>' +
      '</span></li>';
  };
  const a = studio_el('studio-gd-audio'), playing = a && !a.paused && a.getAttribute('data-song') === studio.song;
  return '<section class="gd-slot gd-drops" id="studio-gd-drops"><div class="gd-slothead"><h4>The drops</h4>' +
    '<span class="mono" id="studio-gd-dropcount">' + (gd.drops ? list.length + (list.length === 1 ? ' drop' : ' drops') + ', as you set them' : list.length + ' found by AutoStream') + '</span></div>' +
    '<p class="muted" style="margin:0">Where the bass comes in. Build and drop builds into the main one. Listen, and mark it yourself if it is not where you hear it: ' +
    'click the song to move the playhead, double-click to mark a drop there, drag a drop to move it.</p>' +
    '<div class="gd-dropbox"><canvas id="studio-gd-dropcv" aria-label="The song: its loudness, its parts and its drops"></canvas></div>' +
    '<div class="gd-transport" role="group" aria-label="Player">' +
    '<button type="button" class="btn btn-sm gd-play" data-act="studio-gd" data-gd="play" id="studio-gd-play" aria-label="' + (playing ? 'Pause' : 'Play') + '">' +
      icon(playing ? 'pause' : 'play') + '<span>' + (playing ? 'Pause' : 'Play') + '</span></button>' +
    '<span class="mono gd-time" id="studio-gd-time">' + studio_dur(studio_gdNow()) + ' / ' + studio_dur(sh.seconds) + '</span>' +
    '<input type="range" class="gd-seek" id="studio-gd-seek" min="0" max="1000" step="1" value="' + Math.round(studio_gdNow() / Math.max(1, sh.seconds) * 1000) + '" aria-label="Seek">' +
    '<label class="gd-vol"><span class="muted">Volume</span><input type="range" id="studio-gd-vol" min="0" max="1" step="0.05" value="' + (a ? a.volume : 0.8) + '" aria-label="Volume"></label>' +
    '<button type="button" class="btn btn-sm" data-act="studio-gd" data-gd="drop-into" data-t="' + (main == null ? '' : main) + '"' + (main == null ? ' disabled' : '') + '>Play into the drop</button>' +
    '</div>' +
    '<div class="gd-acts">' +
    '<button type="button" class="btn btn-sm" data-act="studio-gd" data-gd="drop-add" id="studio-gd-dropadd">Mark a drop at the playhead</button>' +
    '<label class="gd-snap"><input type="checkbox" id="studio-gd-snap"' + (gd.snap ? ' checked' : '') + '> Snap to the beat</label>' +
    '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="drop-reset"' + (gd.drops ? '' : ' disabled') + '>Back to AutoStream’s drops</button>' +
    '</div>' +
    (list.length ? '<ol class="gd-droplist" id="studio-gd-droplist">' + list.map(row).join('') + '</ol>'
                 : '<p class="gd-note" id="studio-gd-droplist">' + (gd.drops ? 'No drops: every one was removed.' : 'AutoStream found no drop in this song.') + ' Mark one where you hear the bass come in.</p>') +
    '</section>';
}

/* The drawing: loudness (the song's energy, or its waveform until that is read), its parts named
   along the top, the part the guide plans on, the drops -- AutoStream's hollow, the player's solid,
   the main one taller and named -- and the playhead. Redrawn alone while it plays or a drop is dragged. */
function studio_gdDropDraw() {
  const cv = studio_el('studio-gd-dropcv'), sh = studio.songShape, gd = studio.gd;
  if (!cv || !sh) return;
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 600, H = GD_DROP_H;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + 'px';
  const x = cv.getContext('2d');
  x.setTransform(dpr, 0, 0, dpr, 0, 0);
  x.clearRect(0, 0, W, H);
  const X = t => t / sh.seconds * W, top = GD_DROP_PARTS + GD_DROP_LANE, base = H - 4;
  const warn = studio_tok('--warn'), ok = studio_tok('--ok'), faint = studio_tok('--text-tertiary');
  /* the part the guide plans on */
  const part = studio_gdPart();
  if (part) {
    x.fillStyle = studio_tok('--accent'); x.globalAlpha = 0.1;
    x.fillRect(X(part[0]), GD_DROP_PARTS, X(part[1]) - X(part[0]), H - GD_DROP_PARTS);
    x.globalAlpha = 1;
  }
  /* the parts, named */
  const p = gd.parts && gd.parts.song === studio.song ? gd.parts : null;
  ((p && p.sections) || []).forEach(s => {
    const a = X(s.start), b = X(s.end), hot = s.kind === 'drop' || s.kind === 'riser';
    x.fillStyle = hot ? warn : studio_tok('--border-subtle');
    x.globalAlpha = hot ? 0.45 : 0.6;
    x.fillRect(a, 1, Math.max(1, b - a - 1), GD_DROP_PARTS - 4);
    x.globalAlpha = 1;
    x.fillStyle = studio_tok('--text-secondary'); x.font = '11px system-ui, sans-serif';
    if (b - a > 34) x.fillText(SG_PARTS[s.kind] || s.kind, a + 4, GD_DROP_PARTS - 6);
  });
  /* loudness: the energy curve once read, the waveform's peaks until then */
  const e = p && p.energy && p.energy.length ? p.energy : null, pk = sh.peaks || [];
  x.fillStyle = faint; x.globalAlpha = 0.5;
  for (let i = 0; i < W; i++) {
    const t = i / W * sh.seconds;
    const v = e ? (e[Math.min(e.length - 1, Math.floor(t * (p.hz || 10)))] || 0)
                : (pk[Math.min(pk.length - 1, Math.floor(t / sh.seconds * pk.length))] || 0);
    const h = Math.max(1, Math.min(1, v) * (base - top));
    x.fillRect(i, base - h, 1, h);
  }
  x.globalAlpha = 1;
  /* the drops */
  const main = studio_gdMainDrop(), drag = gd.dropDrag;
  studio_gdDropList().forEach((d, i) => {
    const t = drag && drag.id === d.id && drag.moved ? drag.t : d.t, xx = X(t);
    const isMain = main != null && Math.abs(d.t - main) < 1e-3;
    x.fillStyle = warn; x.globalAlpha = isMain ? 0.9 : 0.5;
    x.fillRect(xx - (isMain ? 1 : 0.75), GD_DROP_PARTS + GD_DROP_LANE - 4, isMain ? 2 : 1.5, H - GD_DROP_PARTS - GD_DROP_LANE);
    x.globalAlpha = 1;
    x.beginPath();
    x.moveTo(xx - 8, GD_DROP_PARTS + 2); x.lineTo(xx + 8, GD_DROP_PARTS + 2); x.lineTo(xx, GD_DROP_PARTS + 17); x.closePath();
    if (d.hand) { x.fillStyle = warn; x.fill(); }
    else { x.fillStyle = studio_tok('--surface'); x.fill(); x.strokeStyle = warn; x.lineWidth = 1.5; x.stroke(); }
    x.fillStyle = warn; x.font = '10px monospace';
    x.fillText(isMain ? 'D' + (i + 1) + ' main' : 'D' + (i + 1), xx + 10, GD_DROP_PARTS + 13);
  });
  /* the playhead */
  x.fillStyle = studio_tok('--bad');
  x.fillRect(X(studio_gdNow()) - 1, GD_DROP_PARTS, 2, H - GD_DROP_PARTS);
  const tl = studio_el('studio-gd-time'), sk = studio_el('studio-gd-seek');
  if (tl) tl.textContent = studio_dur(studio_gdNow()) + ' / ' + studio_dur(sh.seconds);
  if (sk && document.activeElement !== sk) sk.value = String(Math.round(studio_gdNow() / Math.max(1, sh.seconds) * 1000));
}

/* Click to seek, double-click to mark, drag a drop to move it. */
function studio_gdDropWire() {
  const cv = studio_el('studio-gd-dropcv'), gd = studio.gd;
  if (!cv) return;
  const at = e => { const r = cv.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * studio.songShape.seconds; };
  const near = e => {
    const r = cv.getBoundingClientRect(), px = e.clientX - r.left, sh = studio.songShape;
    let best = null, gap = 9;
    studio_gdDropList().forEach(d => { const g = Math.abs(d.t / sh.seconds * r.width - px); if (g < gap) { gap = g; best = d; } });
    return best;
  };
  cv.addEventListener('pointerdown', e => {
    const d = near(e);
    if (d) { gd.dropDrag = {id: d.id, t: d.t, from: e.clientX, moved: false}; cv.setPointerCapture(e.pointerId); return; }
    studio_gdSeek(at(e));
  });
  cv.addEventListener('pointermove', e => {
    const g = gd.dropDrag;
    if (!g) return;
    if (Math.abs(e.clientX - g.from) > 3) g.moved = true;
    if (g.moved) { g.t = at(e); studio_gdDropDraw(); }
  });
  const up = e => {
    const g = gd.dropDrag;
    gd.dropDrag = null;
    if (!g) return;
    if (!g.moved) { studio_gdSeek(g.t); return; }
    gd.drops = studio_dropsOwned(gd.drops, studio.songShape);
    const d = gd.drops.find(x => x.id === g.id);
    if (d) { d.t = studio_mkSnap(at(e), 'studio-gd-snap'); d.auto = false; }
    studio_gdDropsChanged();
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', () => { gd.dropDrag = null; studio_gdDropDraw(); });
  cv.addEventListener('dblclick', e => { if (!near(e)) studio_gdAddDrop(at(e)); });
  const sk = studio_el('studio-gd-seek');
  if (sk) sk.addEventListener('input', () => studio_gdSeek(Number(sk.value) / 1000 * studio.songShape.seconds));
  const vol = studio_el('studio-gd-vol');
  if (vol) vol.addEventListener('input', () => { const a = studio_gdAudio(); if (a) a.volume = Number(vol.value); });
  const snap = studio_el('studio-gd-snap');
  if (snap) snap.addEventListener('change', () => { gd.snap = snap.checked; });
  studio_gdDropDraw();
  studio_gdParts();
}

/* The player's own events, wired once: the button says what it will do, the playhead moves. */
function studio_gdAudioWire() {
  const a = studio_el('studio-gd-audio');
  if (!a || a.getAttribute('data-wired')) return;
  a.setAttribute('data-wired', '1');
  a.volume = 0.8;
  const label = () => {
    const b = studio_el('studio-gd-play');
    if (b) {
      b.innerHTML = icon(a.paused ? 'play' : 'pause') + '<span>' + (a.paused ? 'Play' : 'Pause') + '</span>';
      b.setAttribute('aria-label', a.paused ? 'Play' : 'Pause');
    }
  };
  const tick = () => { studio_gdDropDraw(); if (!a.paused) requestAnimationFrame(tick); };
  a.addEventListener('play', () => { label(); requestAnimationFrame(tick); });
  a.addEventListener('pause', () => { label(); studio_gdDropDraw(); });
  a.addEventListener('seeked', studio_gdDropDraw);
}

function studio_gdDrawSong() {
  const sh = studio.songShape, list = studio.songList || [], part = studio_gdPart();
  const drops = sh ? (sh.drops && sh.drops.length ? sh.drops : (sh.drop ? [sh.drop] : [])) : [];
  return '<div class="gd-q"><h3>Which song?</h3><p class="muted">We pick the best part of it for ' + esc((studio_gdStyle() || {label: 'the style'}).label) + '. You can change it under All settings.</p></div>' +
    '<div class="gd-grid">' + list.map(s => '<button type="button" class="gd-card' + (studio.song && s.path.toLowerCase() === studio.song.toLowerCase() ? ' is-on' : '') +
      '" data-act="studio-gd" data-gd="song" data-path="' + esc(s.path) + '" data-name="' + esc(s.name) + '"><span class="gd-card-name">' + esc(s.name) + '</span></button>').join('') + '</div>' +
    '<div class="gd-acts"><button type="button" class="btn" data-act="studio-gd" data-gd="pick-song">Choose a song file&hellip;</button>' +
    /* the link dialog the Song tab and the Make page use, answering to the guide */
    '<button type="button" class="btn" data-act="studio-yt" data-for="guide">Paste a YouTube link&hellip;</button>' +
    '<span class="muted" id="studio-gd-song-msg"></span></div>' +
    (sh ? '<div class="gd-facts"><span><b>Tempo</b> ' + Math.round(sh.bpm) + ' BPM</span><span><b>Length</b> ' + studio_dur(sh.seconds) + '</span>' +
      '<span><b>Drop</b> ' + (drops.length ? drops.map(d => studio_secs(d)).join(', ') : 'none found') +
      (studio.gd.drops ? ' (as you set them: ' + (studio.gd.drops.length ? studio.gd.drops.map(d => studio_secs(d.t)).join(', ') : 'none') + ')' : '') + '</span>' +
      (part ? '<span><b>Part used</b> ' + studio_secs(part[0]) + ' &rarr; ' + studio_secs(part[1]) + '</span>' : '') + '</div>' +
      studio_gdDropView() : '');
}

/* THE COUNTER, FROM THE PLAN THE CHIP JUDGED: how many of the chosen clips the reel plays, how long it
   runs of its part, and how many more it is short -- the verdict's own numbers, never the page's
   estimate. Until that plan is back it says only what is chosen. Redrawn alone when a verdict lands. */
function studio_gdPlanned() {
  const gd = studio.gd, v = gd.verdict;
  return !gd.filling && v && v.planned && gd.judged && JSON.stringify(gd.judged) === JSON.stringify(studio_gdBody()) ? v : null;
}
function studio_gdCount() {
  const gd = studio.gd, v = studio_gdPlanned(), ids = studio_gdIds();
  const txt = !v ? ids.length + ' chosen' + (gd.filling ? ', planning…' : '')
    : v.used + ' of ' + ids.length + ' in the reel, ' + Math.round(v.length) + ' of ' + Math.round(v.want || v.length) + ' s' +
      (v.more ? ', ' + v.more + ' more needed' : '');
  return '<span class="mono" id="studio-gd-count">' + esc(txt) + '</span>';
}
function studio_gdBar() {
  const v = studio_gdPlanned();
  const pct = v ? Math.min(100, Math.round(v.length / Math.max(1, v.want || v.length) * 100)) : 0;
  return '<div class="gd-bar" id="studio-gd-bar" aria-hidden="true"><i style="width:' + pct + '%"></i></div>';
}
function studio_gdRecount() {
  const c = studio_el('studio-gd-count'), b = studio_el('studio-gd-bar');
  if (c) c.outerHTML = studio_gdCount();
  if (b) b.outerHTML = studio_gdBar();
}

function studio_gdDrawClips() {
  const gd = studio.gd, pools = studio_gdPools();
  const isBD = gd.style === 'drop', isFH = gd.style === 'fasthead', isMT = gd.style === 'montage';
  const ids = studio_gdIds(), out = studio_gdLeftOut();
  const quickIds = ids.filter(id => !(isBD && id === gd.setup));
  const label = (studio_gdStyle() || {label: 'this'}).label;
  const left = out.length ? '<section class="gd-slot gd-left"><div class="gd-slothead"><h4>Chosen, but not in a ' + esc(label) + ' reel</h4>' +
    '<span class="mono">' + out.length + ' left out</span></div><ul class="gd-leftlist">' + out.map(x =>
      '<li><span class="mono">' + esc(x.c.name || x.c.id) + '</span><span class="muted">' + esc(x.why) + '</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="unpick" data-id="' + esc(x.c.id) + '">Remove</button></li>').join('') +
    '</ul></section>' : '';
  const pick = '<div><button type="button" class="btn btn-primary" data-act="studio-gd" data-gd="pickall"' + (gd.filling ? ' disabled' : '') + '>Pick for me</button></div>';
  /* SAID AS IT IS: every clip is here, a page at a time, the best -- favourites first -- on the first
     page. Only the best 48 used to be drawn, so a player with more favourites than that saw nothing
     else and read it as "only my favourites are offered"; Pick for me drew on all of them anyway. */
  const paged = ' are here, ' + GD_PAGE + ' a page, the best first and favourites before the rest. Find, filter and sort them under each slot; Pick for me draws on all of them.';
  if (isFH) {
    const doubles = quickIds.filter(id => studio_gdHsDouble(studio.clipIndex[id] || {})).length;
    return '<div class="gd-q"><h3>Pick the clips, by what they do</h3><p class="muted">Headshots only: a clip with none has nothing for this style. All ' +
      pools.quick.length + ' of your clips with a headshot' + paged + '</p></div>' + pick +
      '<section class="gd-slot"><div class="gd-slothead"><h4>Headshots, one a cut</h4>' + studio_gdCount() + '</div>' + studio_gdBar() +
      '<p class="muted" style="margin:0">' + (doubles ? 'The finale: ' + doubles + ' chosen clip' + (doubles > 1 ? 's have' : ' has') + ' two headshots close together.'
        : 'No chosen clip has two headshots close together, so the reel ends on a single kill, not a multi-kill.') + '</p>' +
      studio_gdBrowser('quick') + '</section>' + left;
  }
  const all = studio_gdClips();
  return '<div class="gd-q"><h3>Pick the clips, by what they do</h3><p class="muted">All ' + all.length + ' of your ' + esc((all[0] || {}).game || '') + ' clips' +
    (isBD ? ' (' + pools.setups.length + ' can be the build, ' + pools.quick.length + ' are quick kills)' : '') + paged +
    (isMT ? ' A montage needs at least four clips with a kill: with fewer it is planned the usual way, not to the song.' : '') + '</p></div>' + pick +
    (isBD ? '<section class="gd-slot"><div class="gd-slothead"><h4>The build: a clutch, an ace or a multi-kill</h4><span class="mono">' + (gd.setup && ids.indexOf(gd.setup) >= 0 ? '1 of 1' : '0 of 1') + '</span></div>' +
      studio_gdBrowser('setup') + '</section>' : '') +
    '<section class="gd-slot"><div class="gd-slothead"><h4>' + (isBD ? 'After the drop: quick kills' : 'Your clips') + (isMT ? ' <span class="muted">(at least 4)</span>' : '') + '</h4>' +
      studio_gdCount() + '</div>' + studio_gdBar() +
    (isBD ? '<p class="muted" style="margin:0">Headshots first. Each clip plays once; a two-kill clip plays both kills only when they are under 1.6 s apart, as a quick run.</p>' : '') +
    studio_gdBrowser('quick') + '</section>' + left;
}

/* ===== EACH SLOT'S CLIP BROWSER =====
   The step keeps its slots -- Build and drop's build and its quick kills, Fast-paced headshot's
   headshots -- because what a clip is FOR is what the folders elsewhere cannot show. Each slot
   browses every clip it can take: a thumbnail card per clip, found by name or label, narrowed by
   favourite, session, map, game mode, kind or chosen-only, sorted, and paged 24 at a time.
   ALL OF THIS IS A VIEW. Searching, filtering, sorting and paging never change a choice, the
   verdict or the request (studio_gdBody), so none of them asks /api/studio/feasible again: they
   redraw the one slot (studio_gdRedrawSlot), never the step. Each slot keeps its own view, so
   paging the quick kills does not move the build's page, and choosing a clip never moves either. */
const GD_PAGE = 24;
const GD_SORTS = [['best', 'Best first'], ['new', 'Newest'], ['kills', 'Most kills'], ['long', 'Longest']];
const GD_KINDS = [['hs', 'Headshot', c => studio_gdHs(c) > 0], ['multi', 'Multi-kill', c => (c.kills || []).length >= 2],
                  ['big', 'Clutch, ace or last alive', c => studio_gdBig(c)]];

/* What a slot offers, in its best-first order, which of them are chosen, and what a click does.
   A chosen clip is always among them -- one counted but nowhere to be found could not be taken
   out again -- even when it is not of the slot's kind (a build clip moved into the quick kills). */
function studio_gdSlot(slot) {
  const gd = studio.gd, pools = studio_gdPools();
  if (slot === 'setup') {
    const list = pools.setups.slice(), own = gd.setup && studio.clipIndex[gd.setup];
    if (own && list.indexOf(own) < 0 && !studio_gdWhyNot(own, gd.style)) list.push(own);
    return {list: list, on: c => gd.setup === c.id, act: 'setup', none: 'None of your clips has three kills or a clutch label.'};
  }
  const list = pools.quick.slice(), seen = {};
  list.forEach(c => { seen[c.id] = 1; });
  studio_gdIds().filter(id => !(gd.style === 'drop' && id === gd.setup) && !seen[id]).forEach(id => list.push(studio.clipIndex[id]));
  return {list: list, on: c => gd.quick.includes(c.id), act: 'quick',
          none: gd.style === 'fasthead' ? 'None of your clips has a kill read as a headshot.' : 'None of your clips has a kill read in it.'};
}
function studio_gdView(slot) {
  const gd = studio.gd;
  gd.views = gd.views || {};
  if (!gd.views[slot]) gd.views[slot] = {q: '', fav: 'any', run: '', map: '', mode: '', kind: '', chosen: false, sort: 'best', page: 1};
  return gd.views[slot];
}
function studio_gdNarrowed(v) { return !!(v.q.trim() || v.fav !== 'any' || v.run || v.map || v.mode || v.kind || v.chosen); }
/* A clip with no match record -- CS2, an import, a run whose record was never fetched -- is said as unknown, not left out. */
function studio_gdMapOf(c) { return c.map || 'Unknown map'; }
function studio_gdModeOf(c) { return c.mode || 'Unknown mode'; }

/* The values one filter can take in this slot, each with how many clips have it. */
function studio_gdFacet(list, key, name, order) {
  const by = {};
  list.forEach(c => { const k = key(c); if (!by[k]) by[k] = {v: k, label: name(c), n: 0, c: c}; by[k].n++; });
  return Object.values(by).sort(order || ((a, b) => (b.n - a.n) || a.label.localeCompare(b.label)));
}

function studio_gdFiltered(slot, s) {
  const v = studio_gdView(slot), q = v.q.trim().toLowerCase(), kind = GD_KINDS.find(k => k[0] === v.kind);
  const rank = {};
  s.list.forEach((c, i) => { rank[c.id] = i; });
  const best = (a, b) => rank[a.id] - rank[b.id];
  const sorts = {
    best: best,
    new: (a, b) => ((b.when || 0) - (a.when || 0)) || ((b.start || 0) - (a.start || 0)) || best(a, b),
    kills: (a, b) => ((b.kills || []).length - (a.kills || []).length) || best(a, b),
    long: (a, b) => ((Number(b.duration) || 0) - (Number(a.duration) || 0)) || best(a, b)
  };
  return s.list.filter(c =>
    (v.fav === 'any' || (v.fav === 'fav') === !!c.fav) &&
    (!v.run || c.folder === v.run) && (!v.map || studio_gdMapOf(c) === v.map) && (!v.mode || studio_gdModeOf(c) === v.mode) &&
    (!kind || kind[2](c)) && (!v.chosen || s.on(c)) &&
    (!q || [c.name || c.id, (c.labels || []).join(' '), c.caption || '', c.folderLabel || '', c.map || '', c.mode || '']
      .join(' ').toLowerCase().indexOf(q) >= 0)
  ).sort(sorts[v.sort] || best);
}

/* THE TOOLS. A filter is offered only with the values that occur in this slot, each with its count,
   and only when it could narrow the slot at all: a map filter over clips all from one map, or a
   session filter over one session, is a control that does nothing. */
function studio_gdTools(slot, s) {
  const v = studio_gdView(slot), list = s.list, n = list.length;
  if (!n) return '';
  const sel = (k, all, aria, items) => {
    if (v[k] && !items.some(o => o.v === v[k])) v[k] = '';   /* a value no clip here has any more */
    if (!items.length || (!v[k] && !items.some(o => o.n < n))) return '';
    return '<select class="select" id="studio-gd-' + k + '-' + slot + '" data-gdview="' + k + '" data-slot="' + slot + '" aria-label="' + aria + '">' +
      '<option value="">' + esc(all) + '</option>' + items.map(o => '<option value="' + esc(o.v) + '"' + (v[k] === o.v ? ' selected' : '') + '>' +
        esc(o.label) + ' (' + o.n + ')</option>').join('') + '</select>';
  };
  const favs = list.filter(c => c.fav).length, chosen = list.filter(s.on).length;
  const seg = (favs && favs < n) || v.fav !== 'any' ? '<div class="seg" role="group" aria-label="Favourites">' +
    [['any', 'All (' + n + ')'], ['fav', 'Favourites (' + favs + ')'], ['other', 'Not favourites (' + (n - favs) + ')']].map(o =>
      '<button type="button" class="seg-btn' + (v.fav === o[0] ? ' is-active' : '') + '" data-act="studio-gd" data-gd="view" data-slot="' + slot +
      '" data-k="fav" data-v="' + o[0] + '" aria-pressed="' + (v.fav === o[0]) + '">' + esc(o[1]) + '</button>').join('') + '</div>' : '';
  /* the recording runs, newest first, as the library names them */
  const runs = studio_gdFacet(list, c => c.folder || '', c => c.folderLabel || 'Another run', (a, b) => (b.c.when || 0) - (a.c.when || 0));
  const kinds = GD_KINDS.map(k => ({v: k[0], label: k[1], n: list.filter(k[2]).length})).filter(o => o.n);
  return '<div class="gd-tools">' +
    '<input class="input" id="studio-gd-find-' + slot + '" data-slot="' + slot + '" type="search" autocomplete="off" placeholder="Find a clip by name or label" aria-label="Find a clip by name or label" value="' + esc(v.q) + '">' +
    seg +
    sel('run', 'Every session', 'Session', runs) +
    sel('map', 'Every map', 'Map', studio_gdFacet(list, studio_gdMapOf, studio_gdMapOf)) +
    sel('mode', 'Every game mode', 'Game mode', studio_gdFacet(list, studio_gdModeOf, studio_gdModeOf)) +
    sel('kind', 'Every kind', 'Kind', kinds) +
    (chosen || v.chosen ? '<button type="button" class="btn btn-sm" data-act="studio-gd" data-gd="view" data-slot="' + slot + '" data-k="chosen" data-v="' +
      (v.chosen ? '' : '1') + '" aria-pressed="' + !!v.chosen + '">Chosen only (' + chosen + ')</button>' : '') +
    (n > 1 ? '<select class="select" id="studio-gd-sort-' + slot + '" data-gdview="sort" data-slot="' + slot + '" aria-label="Sort">' +
      GD_SORTS.map(o => '<option value="' + o[0] + '"' + (v.sort === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>' : '') +
    '</div>';
}

/* One page of cards, what it is out of, and the pager. The page is clamped, never reset: a filter
   that leaves fewer pages shows the last there is, and a choice -- which redraws the step -- stays put. */
function studio_gdResults(slot, s) {
  const v = studio_gdView(slot), l = studio_gdFiltered(slot, s);
  const pages = Math.max(1, Math.ceil(l.length / GD_PAGE));
  v.page = Math.min(Math.max(1, Number(v.page) || 1), pages);
  const from = (v.page - 1) * GD_PAGE, shown = l.slice(from, from + GD_PAGE), narrowed = studio_gdNarrowed(v);
  const count = l.length ? 'Showing ' + (from + 1) + '–' + (from + shown.length) + ' of ' + l.length +
    (narrowed ? ' that match, of ' + s.list.length : '') : '';
  return '<p class="gd-count muted" id="studio-gd-count-' + slot + '">' + count + '</p>' +
    '<div class="gd-grid gd-clips" id="studio-gd-' + slot + 'grid">' + (shown.map(c => studio_gdCard(c, s.on(c), s.act)).join('') ||
      (s.list.length ? '<p class="muted">No clip matches. <button type="button" class="btn btn-sm btn-ghost" data-act="studio-gd" data-gd="view-clear" data-slot="' + slot + '">Clear the filters</button></p>'
                     : '<p class="muted">' + esc(s.none) + '</p>')) + '</div>' +
    studio_gdPager(slot, v.page, pages);
}
function studio_gdPager(slot, page, pages) {
  if (pages < 2) return '';
  const btn = (p, text, aria, on, off) => '<button type="button" class="btn btn-sm' + (on ? ' btn-primary' : ' btn-ghost') + '" data-act="studio-gd" data-gd="page" data-slot="' + slot +
    '" data-v="' + p + '" aria-label="' + aria + '"' + (on ? ' aria-current="page"' : '') + (off ? ' disabled' : '') + '>' + text + '</button>';
  let html = btn(page - 1, '‹ Prev', 'Previous page', false, page <= 1), last = 0;
  /* the first and last pages, and two either side of this one: 1 ... 4 5 [6] 7 8 ... 14 */
  for (let i = 1; i <= pages; i++) {
    if (i !== 1 && i !== pages && Math.abs(i - page) > 2) continue;
    if (i - last > 1) html += '<span class="gd-gap" aria-hidden="true">…</span>';
    html += btn(i, String(i), 'Page ' + i, i === page, false);
    last = i;
  }
  return '<nav class="gd-pager" aria-label="Pages">' + html + btn(page + 1, 'Next ›', 'Next page', false, page >= pages) + '</nav>';
}
function studio_gdBrowser(slot, s) {
  s = s || studio_gdSlot(slot);
  return '<div class="gd-browse" id="studio-gd-browse-' + slot + '">' + studio_gdTools(slot, s) +
    '<div class="gd-results" id="studio-gd-res-' + slot + '">' + studio_gdResults(slot, s) + '</div></div>';
}

/* A CLIP AS A CARD: its frame at the first kill, what it is, how long, from which match and when,
   and whether it is chosen. The card's body chooses it; Play and Edit are beside it, not in it. */
function studio_gdCard(c, on, act) {
  const at = Math.max(0, ((c.kills || [])[0] || 0) - 0.3).toFixed(2);
  const k = (c.kills || []).length, meta = [c.map, c.mode, c.folderLabel].filter(Boolean);
  return '<div class="gd-clip' + (on ? ' is-on' : '') + '" data-id="' + esc(c.id) + '">' +
    '<button type="button" class="gd-clip-hit" data-act="studio-gd" data-gd="' + act + '" data-id="' + esc(c.id) + '" aria-pressed="' + on + '"' +
      ' title="' + (on ? 'Chosen. Click to take it out.' : 'Click to choose it.') + '">' +
    '<span class="gd-thumb"><img class="gd-thumbimg" loading="lazy" alt="" width="320" height="180" src="' +
      studio_media('/api/studio/thumb', c.path, '&t=' + at + '&v=' + (c.mtime || 0)) + '">' +
      '<span class="gd-len mono">' + studio_dur(c.duration) + '</span><span class="gd-tick" aria-hidden="true">' + icon('check') + '</span></span>' +
    '<span class="gd-tags">' + (studio_gdHs(c) ? '<i class="gd-hs">Headshot</i>' : '<i>Body</i>') +
      (c.fav ? '<i class="gd-fav" title="A favourite">&#9733;</i>' : '') + (k > 1 ? '<i>' + k + ' kills</i>' : '') +
      (c.labels || []).slice(0, 2).map(x => '<i>' + esc(x) + '</i>').join('') + '</span>' +
    '<span class="gd-name mono">' + esc(c.name || c.id) + '</span>' +
    (meta.length ? '<span class="gd-meta">' + esc(meta.join(' · ')) + '</span>' : '') + '</button>' +
    '<div class="gd-clip-acts">' +
      '<button type="button" class="btn btn-sm" data-act="studio-gd" data-gd="clip-play" data-slot="' + act + '" data-id="' + esc(c.id) + '">' + icon('play') + '<span>Play</span></button>' +
      '<button type="button" class="btn btn-sm btn-ghost" data-act="studio-gd" data-gd="clip-edit" data-id="' + esc(c.id) + '" title="Trim and cut it on the Clips page">' +
        icon('scissors') + '<span>Edit</span></button></div></div>';
}

/* Redraw one slot's browser -- or only its results, which leaves the find box and the filters alone,
   so the caret and the open select stay where the player left them. Never the verdict. */
function studio_gdRedrawSlot(slot, resultsOnly) {
  const host = studio_el(resultsOnly ? 'studio-gd-res-' + slot : 'studio-gd-browse-' + slot);
  if (!host) return;
  const s = studio_gdSlot(slot), had = document.activeElement && host.contains(document.activeElement) ? document.activeElement.id : '';
  if (resultsOnly) host.innerHTML = studio_gdResults(slot, s);
  else host.outerHTML = studio_gdBrowser(slot, s);
  const el = had && studio_el(had);
  if (el) el.focus();
}
/* typing in a find box redraws that slot's results alone, so the box keeps its focus and caret */
function studio_gdFind(e) {
  const t = e.target;
  if (!t || !t.id || t.id.indexOf('studio-gd-find-') !== 0) return;
  const slot = t.getAttribute('data-slot'), v = studio_gdView(slot);
  v.q = t.value; v.page = 1;
  studio_gdRedrawSlot(slot, true);
}
function studio_gdViewChange(e) {
  const t = e.target, k = t && t.getAttribute ? t.getAttribute('data-gdview') : null;
  if (!k) return;
  const slot = t.getAttribute('data-slot'), v = studio_gdView(slot);
  v[k] = t.value; v.page = 1;
  studio_gdRedrawSlot(slot, true);
}

/* ▶ PLAY: the clip in the Studio's own preview, over the guide, with its kills marked along it and
   the choice in reach. Closing it (studio_previewClose) leaves the guide exactly where it was. */
function studio_gdPlayClip(id, slot) {
  if (!studio.clipIndex[id]) return;
  studio_preview(id);
  studio.gd.pv = {id: id, slot: slot === 'setup' ? 'setup' : 'quick'};
  studio_gdPvPick();
}
function studio_gdPvPick() {
  const gd = studio.gd, pv = gd.pv, b = studio_el('studio-preview-pick');
  if (!b) return;
  studio_show('studio-preview-pick', !!pv);
  if (!pv) return;
  const on = pv.slot === 'setup' ? gd.setup === pv.id : gd.quick.includes(pv.id);
  b.classList.toggle('btn-primary', !on);
  b.setAttribute('aria-pressed', String(on));
  b.innerHTML = on ? icon('check') + '<span>' + (pv.slot === 'setup' ? 'The build: take it out' : 'Chosen: take it out') + '</span>'
                   : '<span>' + (pv.slot === 'setup' ? 'Use it as the build' : 'Choose this clip') + '</span>';
}

/* ✎ EDIT: the Clips page's own Trim and cut, for this clip (clip_visit). The guide is left open
   under it, on its step, with its slots' pages and every choice; back from there it is shown
   again. A saved trim re-reads the library -- the clip's length, kills and thumbnail are what the
   trim made them -- and the choice follows the clip. */
function studio_gdEditClip(id) {
  const c = studio.clipIndex[id];
  if (!c || !c.folder || typeof clip_visit !== 'function') { toast('That clip cannot be edited from here.', 'warn'); return; }
  studio.gd.editing = {id: id, path: c.path, folder: c.folder, name: c.name};
  go('clips');
  clip_visit(c.folder, c.path, studio_gdEdited);
}
async function studio_gdEdited(res) {
  const gd = studio.gd, was = gd.editing;
  gd.editing = null;
  go('studio');
  if (!was) return;
  if (res) {
    await studio_load(true);
    /* AN EDIT RE-CUTS THE CLIP UNDER ITS OWN NAME, so its id -- the hash of its path -- normally
       stays. One that comes back under another path is found by that path, or by its name in the
       same run, and takes the old one's place in the draft rather than leaving it. */
    if (!studio.clipIndex[was.id]) {
      const norm = p => String(p || '').split('/').join('\\').toLowerCase(), all = Object.values(studio.clipIndex);
      const now = all.find(c => res.master && norm(c.path) === norm(res.master)) || all.find(c => c.folder === was.folder && c.name === was.name);
      if (now) {
        if (gd.setup === was.id) gd.setup = now.id;
        gd.quick = gd.quick.map(x => x === was.id ? now.id : x);
        was.id = now.id;
      }
    }
    gd.verdict = null;                     /* the clip is not what was judged: asked again */
  }
  if (studio_el('studio-guide-scrim').classList.contains('hide')) return;
  if (res) studio_gdDraw();
  const card = document.querySelector('#studio-gd-body .gd-clip[data-id="' + CSS.escape(was.id) + '"]');
  if (card) card.scrollIntoView({block: 'center'});
}

function studio_gdSeg(name, val, opts) {
  return '<div class="seg" role="group">' + opts.map(o => '<button type="button" class="seg-btn' + (val === o[0] ? ' is-active' : '') + '" data-act="studio-gd" data-gd="set" data-k="' + name + '" data-v="' + o[0] + '" aria-pressed="' + (val === o[0]) + '">' + esc(o[1]) + '</button>').join('') + '</div>';
}
/* THE SONG'S WORDS ON THE REEL, asked on the Look step. The roadmap had lyrics in this step (F9) and the
   step shipped without them -- they were only on the timeline, after a first render -- so a reel made
   step by step could not have them without a second render. Whether a song's words can be found is
   only known when it renders, so they are offered as that: used if found, never promised. */
function studio_gdLyricLooks() { return ((studio.catalog && studio.catalog.lyrics) || {}).looks || []; }
function studio_gdDrawLook() {
  const gd = studio.gd, looks = studio_gdLyricLooks();
  const look = looks.find(l => l.key === gd.lyrics);
  return '<div class="gd-q"><h3>How should it look?</h3><p class="muted">Only what changes the picture. The effects come with the style; the rest is under All settings.</p></div>' +
    '<div class="gd-field"><h4>Shape</h4>' + studio_gdSeg('fmt', gd.fmt, [['vertical', '9:16 Short or Reel'], ['landscape', '16:9 YouTube']]) + '</div>' +
    (gd.fmt === 'vertical' ? '<div class="gd-field"><h4>Framing</h4>' + studio_gdSeg('fit', gd.fit, [['near', 'Near fit'], ['fit', 'Fit the whole picture'], ['zoom', 'Zoom to fill']]) + '</div>' : '') +
    (looks.length ? '<div class="gd-field"><h4>Lyrics</h4>' + studio_gdSeg('lyrics', gd.lyrics, [['off', 'No lyrics']].concat(looks.map(l => [l.key, l.label]))) +
      '<p class="muted" style="margin:0">' + esc(look ? look.blurb : 'The song’s own words, each on its sung syllable; the look, size and place can be changed on the timeline.') +
      ' Used if this song’s lyrics are found when the reel renders; if they are not, the reel has none and says so.</p></div>' : '');
}

/* The facts of the check step, redrawn alone when the verdict lands: redrawing the whole step took the
   name field out from under the player's typing. */
function studio_gdFacts() {
  const gd = studio.gd, s = studio_gdStyle(), ids = studio_gdIds(), out = studio_gdLeftOut();
  const song = studio.song ? studio.song.split(/[\\/]/).pop().replace(/\.[^.]+$/, '') : '';
  const lyr = studio_gdLyricLooks().find(l => l.key === gd.lyrics);
  return '<div class="gd-facts" id="studio-gd-facts"><span><b>Style</b> ' + esc(s ? s.label : '') + '</span><span><b>Song</b> ' + esc(song) + '</span>' +
    '<span><b>Clips</b> ' + ids.length + ' (' + studio_gdKillsIn(ids) + ' kills)' + (out.length ? ', ' + out.length + ' left out' : '') + '</span>' +
    '<span><b>Shape</b> ' + (gd.fmt === 'vertical' ? '9:16' : '16:9') + '</span>' +
    '<span><b>Lyrics</b> ' + esc(lyr ? lyr.label + ', if found' : 'None') + '</span>' +
    (gd.verdict && gd.verdict.length ? '<span><b>Length</b> ' + Math.round(gd.verdict.length) + ' s</span>' : '') + '</div>';
}
function studio_gdDrawCheck() {
  const gd = studio.gd;
  return '<div class="gd-q"><h3>Check and make</h3><p class="muted">Planned, not rendered yet. This is what the reel will be.</p></div>' +
    studio_gdFacts() +
    '<div class="gd-field"><label class="field-label" for="studio-gd-name">Name</label>' +
    '<input class="input" id="studio-gd-name" maxlength="80" placeholder="' + esc(studio_gdDefaultName()) + '" value="' + esc(gd.name || '') + '"></div>' +
    '<p class="muted">After it is rendered we read the finished reel back and check every kill is on its beat, in focus and not repeated.</p>';
}

/* The name a reel gets when none is typed: the song's title and the style, not "Build and drop reel"
   for every one. "Y2K, bbno$ - Lalala (Official Video) [N2Y2vQ-1m7M]" is "Lalala". */
function studio_gdDefaultName(d) {
  const s = studio_gdStyle((d || studio.gd).style);
  let song = studio.song ? studio.song.split(/[\\/]/).pop().replace(/\.[^.]+$/, '') : '';
  song = song.replace(/\s*\[[^\]]*\]/g, '').replace(/\s*\((official|lyric|audio|music)[^)]*\)/ig, '');
  if (song.includes(' - ')) song = song.split(' - ').slice(1).join(' - ');
  return ((song.trim() ? song.trim() + ' ' : '') + (s ? s.label.toLowerCase() : 'reel')).replace(/^./, c => c.toUpperCase());
}

/* THE CHIP: the server's verdict, or the one thing known without asking -- or, on the last step,
   why the reel was not made just now */
function studio_gdChip() {
  const gd = studio.gd, el = studio_el('studio-gd-chip');
  let v = gd.verdict;
  if (gd.step === 0) {
    v = (!gd.style && !gd.auto) ? {level: 'warn', text: 'Pick a style, or pick a song and we will choose one.'}
      : {level: 'ok', text: gd.style ? 'Good. Next: the song.' : 'Pick a song next and we will choose the style.'};
  }
  if (gd.step >= 1 && !v) v = {level: 'ok', text: 'Checking this against your song and clips…'};
  if (gd.step === 4 && gd.held) v = gd.held;
  const label = v.dot || {ok: 'Works', warn: 'Will work, but', bad: "Won't work"}[v.level];
  el.className = 'gd-chip ' + v.level;
  /* A STYLE THAT NEEDS A DROP, ON A SONG WITHOUT ONE: the drop may be there and missed, and the
     player can hear it. Marking it is offered first; another song is still offered beside it. */
  const markIt = v.fix === 'pick-song' && studio.songShape && (studio_gdStyle() || {}).drop && studio_gdMainDrop() == null;
  /* `why`: Add or Pick for me could not fill it, and says so -- with no button that would add nothing */
  const fix = v.fix && !(v.why && v.fix === 'pick-clips') ? '<button type="button" class="btn ' + (markIt ? '' : 'btn-primary ') + 'btn-sm" data-act="studio-gd" data-gd="fix" data-fix="' + esc(v.fix) + '">' + esc(v.fix_label || 'Fix it') + '</button>' : '';
  el.innerHTML = '<span class="gd-dot">' + esc(label) + '</span><p>' + esc(v.text) + (v.why ? ' ' + esc(v.why) : '') + '</p>' +
    (markIt ? '<span class="gd-acts"><button type="button" class="btn btn-primary btn-sm" data-act="studio-gd" data-gd="fix" data-fix="mark-drop">Mark the drop yourself</button>' + fix + '</span>'
            : fix || '<span></span>');
}

/* NOTHING THE STYLE CAN USE, said as that: clips were chosen and every one is left out, or the
   library has none of the kind. The server would only hear "no clips" and say none were chosen. */
function studio_gdNone(d) {
  if (studio_gdIds(d).length) return null;
  const out = studio_gdLeftOut(d), label = (studio_gdStyle(d.style) || {label: 'This style'}).label;
  if (out.length) return {level: 'bad', text: 'None of the chosen clips can be in a ' + label + ' reel: ' + out[0].why + '.',
                          fix: 'pick-clips', fix_label: 'Pick for me'};
  if (!studio_gdPools(d.style, d.setup).quick.length && !(d.style === 'drop' && studio_gdPools('drop', '').setups.length))
    return {level: 'bad', text: d.style === 'fasthead' ? 'None of your clips has a kill read as a headshot.' : 'None of your clips has a kill read in it.'};
  return null;                             /* none chosen yet: the server says so, with Pick for me */
}

/* Ask the server once the last answer has settled; a newer question makes an older answer stale.
   The body asked about is kept beside the answer (`judged`): it is the plan's body, to the byte. */
function studio_gdAsk() {
  const gd = studio.gd;
  clearTimeout(gd.timer);
  if (!gd.style || !studio.song) { gd.verdict = null; studio_gdChip(); return; }
  if (gd.filling) return;                  /* the fill answers with its own verdict */
  /* the verdict already in hand judged exactly this request: asking again plans the same reel */
  if (gd.verdict && gd.verdict.planned && gd.judged && JSON.stringify(gd.judged) === JSON.stringify(studio_gdBody())) return;
  const ticket = ++gd.asked;
  gd.timer = setTimeout(async () => {
    const body = studio_gdBody(), none = studio_gdNone(gd);
    const got = none ? {ok: true, verdict: none} : await API.post('/api/studio/feasible', body).catch(() => null);
    if (ticket !== gd.asked || gd.busy) return;
    gd.verdict = got && got.ok ? Object.assign({}, got.verdict, {length: got.length})
                               : {level: 'warn', text: 'Could not check this against your clips just now.'};
    gd.judged = body;
    studio_gdChip();
    if (gd.step === 2) studio_gdRecount();
    if (gd.step === 4) {
      const f = studio_el('studio-gd-facts');
      if (f) f.outerHTML = studio_gdFacts();
      studio_el('studio-gd-next').disabled = gd.busy || gd.verdict.level === 'bad';
    }
  }, 250);
}

async function studio_gdUseSong(path, name) {
  const msg = studio_el('studio-gd-song-msg');
  if (msg) msg.textContent = 'Finding the beat…';
  const was = studio.song;
  const ok = await studio_useSong(path, name);
  if (!ok) { if (msg) msg.textContent = 'Could not read that song.'; return false; }
  const gd = studio.gd;
  gd.verdict = null;
  if (was !== studio.song) { gd.drops = null; gd.head = 0; }   /* a drop belongs to the song it was marked on */
  if (gd.auto) {
    gd.step = 0; gd.style = ''; gd.autoWhy = null;
    studio_gdDraw();
    await studio_gdAutoStyle();
  }
  studio_gdDraw();
  return true;
}

function studio_gdFix(fix) {
  const gd = studio.gd;
  if (fix.indexOf('style:') === 0) { gd.style = fix.slice(6); gd.auto = false; }
  else if (fix === 'pick-song') { gd.step = 1; }
  else if (fix === 'mark-drop' || fix === 'mark-drop:drop') {
    if (fix === 'mark-drop:drop') { gd.style = 'drop'; gd.auto = false; gd.verdict = null; }
    gd.step = 1;
    studio_gdDraw();
    const v = studio_el('studio-gd-drops');
    if (v) v.scrollIntoView({block: 'nearest'});
    const add = studio_el('studio-gd-dropadd');
    if (add) add.focus();
    return;
  }
  else if (fix === 'pick-clips') {   /* adds; keeps what was chosen -- what the plan says it is short, chosen by the plan */
    gd.step = 2;
    return studio_gdPickAll(true);
  }
  else if (fix === 'format:vertical') { gd.fmt = 'vertical'; }
  else if (fix === 'part:fit') {
    /* THE PART THE SONG CAN CARRY: the seconds the plan really covers (the verdict's span), made the
       player's own part -- so the reel is judged as what it is, not as a longer one it cannot be */
    const sp = gd.verdict && gd.verdict.span, mk = studio.mk;
    if (sp && sp[1] > sp[0]) { mk.mode = 'part'; mk.start = sp[0]; mk.end = sp[1]; mk.touched = true; }
  }
  gd.verdict = null;
  studio_gdDraw();
}

function studio_gdAllSettings() {
  if (!studio_gdIds().length) { toast('Pick the clips first: the full page starts from them.', 'warn'); return; }
  const step = studio.gd.step;
  studio_gdHandOff();
  studio_gdClose();
  studio.mkFrom = {step: step};                 /* so "Back to the steps" returns to it */
  studio_openMake({fromGuide: true});
}

/* A NEW REEL'S DRAFT, STARTED AFRESH: the part drawn by the page again, no marks, the song's own drops.
   Opening the guide from the clips is a new reel; the draft of the last one is not carried into it. */
function studio_tmFresh() {
  const mk = studio.mk;
  mk.hand = []; mk.edited = false; mk.planned = null; mk.drops = null; mk.sel = {};
  mk.touched = false; mk.mode = 'part'; mk.planAsk = (mk.planAsk || 0) + 1;
  mk.of = 'new';
  studio.mkAnchors = null;
}

/* MAKE, FROM THE GUIDE ITSELF. It used to open All settings and build from there, so the player
   watched a page they had not asked for, its Build button greyed for the minute the plan takes,
   with a name nobody had asked them for. Now the guide plans in place, from the body the chip
   judged, and opens the timeline. */
async function studio_gdMake() {
  const gd = studio.gd;
  if (gd.busy) return;
  const nameEl = studio_el('studio-gd-name');
  if (nameEl) gd.name = nameEl.value;
  const body = studio_gdBody();
  const run = ++gd.run;
  gd.busy = true; gd.held = null;
  studio_gdDraw();
  const next = studio_el('studio-gd-next');
  const chip = (text, level, dot) => {
    if (run !== gd.run) return;
    const el = studio_el('studio-gd-chip');
    el.className = 'gd-chip ' + level;
    el.innerHTML = '<span class="gd-dot">' + esc(dot) + '</span><p>' + esc(text) + '</p><span></span>';
  };
  let made = false;
  try {
    made = await studio_build({btn: next, body: body,
      held: t => { if (run === gd.run) gd.held = {level: 'warn', text: t, dot: 'Not now'}; },
      say: (t, failed) => {
        if (failed) { if (run === gd.run) gd.held = {level: 'bad', text: t}; chip(t, 'bad', "Won't work"); }
        else chip(t + ' This takes about a minute; the reel opens on the timeline when it is planned.', 'ok', 'Making it');
      }});
  } finally {
    if (run === gd.run) {
      gd.busy = false;
      /* the next reel is a new one: its own name and the song's own drops, not this one's */
      if (made) { studio_gdHandOff(body); gd.name = ''; studio_tmFresh(); }
    }
    if (!studio_el('studio-guide-scrim').classList.contains('hide')) studio_gdDraw();
  }
}

function studio_gdAct(b) {
  const gd = studio.gd, what = b.getAttribute('data-gd');
  if (what === 'close') return studio_gdClose();
  /* Back while it plans lets go of the plan and goes back: it used to look live and do nothing */
  if (what === 'back' && gd.busy) { studio_gdDetach(); gd.step = 3; gd.verdict = null; return studio_gdDraw(); }
  /* a kill mark in the preview: a seek, in the library's preview as in the guide's */
  if (what === 'pv-seek') { const v = studio_el('studio-preview-video'), t = Number(b.getAttribute('data-t')); if (v && isFinite(t)) v.currentTime = t; return; }
  if (gd.busy) return;                     /* planning: Back and Close are what is offered */
  if (what === 'view' || what === 'page' || what === 'view-clear') return studio_gdViewAct(what, b);
  if (what === 'clip-play') return studio_gdPlayClip(b.getAttribute('data-id'), b.getAttribute('data-slot'));
  if (what === 'clip-edit') return studio_gdEditClip(b.getAttribute('data-id'));
  if (what === 'pv-pick') {
    if (!gd.pv) return;
    studio_gdToggle(gd.pv.slot, gd.pv.id);
    studio_gdDraw();
    return studio_gdPvPick();
  }
  gd.held = null;
  if (what === 'all') return studio_gdAllSettings();
  if (what === 'fix') return studio_gdFix(b.getAttribute('data-fix'));
  if (what === 'song') { studio_gdUseSong(b.getAttribute('data-path'), b.getAttribute('data-name')); return; }
  if (what === 'pick-song') {
    studio_pickSong().then(() => { if (gd.auto && studio.song) studio_gdUseSong(studio.song, ''); else studio_gdDraw(); });
    return;
  }
  if (what === 'more') { const d = document.querySelector('.gd-more'); if (d) { d.open = true; d.scrollIntoView({block: 'nearest'}); } return; }
  /* the Song step's player and drops (studio_gdDropView) */
  if (what === 'play') return studio_gdPlay();
  if (what === 'drop-into') { const t = Number(b.getAttribute('data-t')); if (isFinite(t)) studio_gdPlayInto(t); return; }
  if (what === 'drop-add') return studio_gdAddDrop(studio_gdNow());
  if (what === 'drop-del') return studio_gdDelDrop(b.getAttribute('data-id'));
  if (what === 'drop-nudge') return studio_gdNudgeDrop(b.getAttribute('data-id'), Number(b.getAttribute('data-by')));
  if (what === 'drop-reset') { gd.drops = null; gd.verdict = null; return studio_gdDraw(); }
  if (what === 'step') { gd.step = Number(b.getAttribute('data-i')); }
  else if (what === 'back') { gd.step = Math.max(0, gd.step - 1); }
  else if (what === 'next') { if (gd.step === 4) return studio_gdMake(); gd.step++; }
  else if (what === 'style') {
    gd.style = b.getAttribute('data-key'); gd.auto = false; gd.autoWhy = null;
    /* a build clip chosen for Build and drop is still one of the player's clips in another style */
    if (gd.style !== 'drop' && gd.setup && gd.quick.indexOf(gd.setup) < 0) gd.quick = [gd.setup].concat(gd.quick);
    gd.verdict = null;
  }
  else if (what === 'auto') { gd.auto = true; gd.style = ''; gd.autoWhy = null; gd.step = 1; gd.verdict = null; }
  else if (what === 'setup' || what === 'quick' || what === 'unpick') studio_gdToggle(what, b.getAttribute('data-id'));
  else if (what === 'pickall') return studio_gdPickAll(false);
  else if (what === 'set') { gd[b.getAttribute('data-k')] = b.getAttribute('data-v'); gd.verdict = null; }
  studio_gdDraw();
}
/* A clip chosen or taken out, from its card, the left-out list or the player. A choice is the one
   thing on the Clips step the verdict is asked again for. */
function studio_gdToggle(what, id) {
  const gd = studio.gd;
  if (what === 'setup') { gd.setup = gd.setup === id ? '' : id; gd.quick = gd.quick.filter(x => x !== gd.setup); }
  else {
    const off = what === 'unpick' || gd.quick.indexOf(id) >= 0;
    gd.quick = off ? gd.quick.filter(x => x !== id) : gd.quick.concat([id]);
    if (off && gd.setup === id) gd.setup = '';   /* taken out is taken out, from the build slot too */
  }
  gd.verdict = null;
}
/* THE CLIP BROWSERS' VIEWS: which clips a slot shows, never which are chosen -- so one slot is
   redrawn and nothing is asked again. A filter, a search or a sort starts again from page one. */
function studio_gdViewAct(what, b) {
  const slot = b.getAttribute('data-slot'), v = studio_gdView(slot);
  if (what === 'page') {
    v.page = Number(b.getAttribute('data-v')) || 1;
    studio_gdRedrawSlot(slot, true);
    const top = studio_el('studio-gd-count-' + slot);
    if (top) top.scrollIntoView({block: 'nearest'});
    return;
  }
  if (what === 'view-clear') Object.assign(v, {q: '', fav: 'any', run: '', map: '', mode: '', kind: '', chosen: false});
  else { const k = b.getAttribute('data-k'), val = b.getAttribute('data-v'); v[k] = k === 'chosen' ? !!val : val; }
  v.page = 1;
  studio_gdRedrawSlot(slot, false);
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
