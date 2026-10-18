"""Every action the Studio can take, named once, in one list.

WHY THIS FILE EXISTS
    The Studio page declared 147 distinct `data-act` strings and eight key
    bindings inside a single `keydown` block, and nothing in the program could
    enumerate either one. That is not a tidiness complaint: it is the reason
    the page had no command palette, no key sheet and no way to rebind
    anything. You cannot search a list that does not exist.

    So the names come out of the markup and into one table. The table is
    Python rather than JS because three different things have to read it and
    only one of them is a browser:

      1. the page, which renders the palette and the key sheet from it;
      2. /api/studio/commands, so the browser tier can ask what the editor can
         do and run a command by name instead of hunting for its button;
      3. the offline suite, which holds the three rules at the bottom of this
         docstring without opening a browser.

WHAT A COMMAND IS
    {id, label, scope, act, args, keys, palette}

    `act` is the `data-act` the page already dispatches, and `args` the data
    attributes that pick which one -- so a command RUNS by pressing the control
    that is already there. Nothing is reimplemented, which is the only way a
    registry over 147 existing actions can be added without changing what any
    of them does. A command with `act: None` is keyboard-only and names a
    function in the page's own run table (studio_cmdRun).

    `palette` is whether a human should be offered it by name. A parameterised
    action -- seek to this x, pick that clip, drag this dial one step -- is in
    the registry because the registry must be complete, and out of the palette
    because "Seek" with no place to seek to is not an offer.

THE SCOPE ORDER IS LOAD-BEARING
    SCOPES is in the exact precedence the page's keydown block uses: importer,
    then the effect picker, then Escape, then text fields, then the song pane,
    then "a focused button owns Space, Backspace and Enter", then the timeline.
    Lose the order and Space on a focused button starts playback instead of
    pressing the button. The order lives here so the key sheet prints it and
    the tests can check against it; the handler itself is unchanged until a
    test replays every key in every pane state.

THE THREE RULES, ALL OFFLINE (tests/test_studio_commands.py)
    1. Every `data-act` the page renders has at least one command naming it,
       and every command names an act the page renders. Drift in either
       direction is a command nobody can run or a control nobody can find.
    2. No key is bound twice in one scope.
    3. No binding names a command that does not exist.

    Rules 2 and 3 are the two the ArtCraft specifications carry; rule 1 is ours,
    because our commands stand on controls that are already on the page.

NAMING
    Ids are `<scope>.<verb>` and are a contract: the browser tier calls them by
    name and a rebinding would be stored against them. Labels are the user's
    words, not the code's -- they are what the palette shows.
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------- the scopes
#
# In the page's own keydown precedence. `blurb` is printed on the key sheet so
# a reader knows when a scope's keys are the ones in force.
SCOPES: tuple[dict, ...] = (
    {"id": "import", "label": "Importing a clip",
     "blurb": "While the importer is open, it takes the keys first."},
    {"id": "picker", "label": "The effect picker",
     "blurb": "While the picker is open."},
    {"id": "song", "label": "The song pane",
     "blurb": "While the song is open and a part is being shaped."},
    {"id": "timeline", "label": "The timeline",
     "blurb": "While the editor is open and nothing above has the keys."},
    {"id": "make", "label": "Making a reel",
     "blurb": "The Make a reel dialog, and the part of the song it is cut to."},
    {"id": "intro", "label": "The opening clip",
     "blurb": "Choosing and trimming what the reel opens on."},
    {"id": "facecam", "label": "Your camera",
     "blurb": "Attaching a camera video and lining it up."},
    {"id": "looks", "label": "Looks and the drawers",
     "blurb": "The look, the drawers it is dealt from, and the examples."},
    {"id": "library", "label": "Clips and reels",
     "blurb": "Picking clips, and the reels already made."},
    {"id": "studio", "label": "Anywhere in the Studio",
     "blurb": "These work wherever you are on the page."},
)

SCOPE_IDS: tuple[str, ...] = tuple(s["id"] for s in SCOPES)


def _c(cid: str, label: str, scope: str, act: str | None = None, *,
       args: dict | None = None, keys: tuple[str, ...] = (),
       palette: bool = True, why: str = "") -> dict:
    """One row. `why` is shown under the label when the command cannot run."""
    return {"id": cid, "label": label, "scope": scope, "act": act,
            "args": args or {}, "keys": list(keys), "palette": palette,
            "why": why}


# ------------------------------------------------------------- the commands
#
# Grouped by scope, in the order the key sheet prints them.
COMMANDS: list[dict] = [

    # -- anywhere ----------------------------------------------------------
    _c("studio.palette", "Run a command…", "studio", "studio-palette",
       keys=("Ctrl+K",)),
    _c("studio.keys", "Show the keys", "studio", "studio-keys", keys=("?",)),
    _c("studio.palette-close", "Close the command list", "studio",
       "studio-pal-close", palette=False),
    _c("studio.keys-close", "Close the key sheet", "studio",
       "studio-keys-close", palette=False),
    _c("studio.escape", "Close whatever is open", "studio", None,
       keys=("Escape",), palette=False),
    _c("studio.refresh", "Look for new clips and reels", "studio",
       "studio-refresh"),
    _c("studio.go-clips", "Go to Clips", "studio", "studio-tab",
       args={"data-tab": "clips"}),
    _c("studio.go-reels", "Go to Reels", "studio", "studio-tab",
       args={"data-tab": "reels"}),
    _c("studio.go-looks", "Go to Looks", "studio", "studio-tab",
       args={"data-tab": "looks"}),
    _c("studio.go-timeline", "Go to the Timeline", "studio", "studio-tab",
       args={"data-tab": "timeline"},
       why="Open a reel first — there is no timeline without one."),
    _c("studio.go-song", "Go to the Song", "studio", "studio-tab",
       args={"data-tab": "song"},
       why="Open a reel first."),
    _c("studio.go-facecam", "Go to the Facecam", "studio", "studio-tab",
       args={"data-tab": "facecam"},
       why="Open a reel first."),
    _c("studio.go-back", "Back to the timeline", "studio", "studio-tab-go",
       palette=False),

    # -- the timeline ------------------------------------------------------
    _c("timeline.play", "Play or pause the reel", "timeline", "studio-play",
       keys=("Space",)),
    _c("timeline.next-shot", "Go to the next shot", "timeline", None,
       keys=("ArrowRight",)),
    _c("timeline.prev-shot", "Go to the previous shot", "timeline", None,
       keys=("ArrowLeft",)),
    _c("timeline.remove-shot", "Remove the selected shot", "timeline",
       "studio-remove",
       keys=("Delete", "Backspace"),
       why="A reel keeps at least one shot, and this is the last one."),
    _c("timeline.move-left", "Move the shot earlier", "timeline",
       "studio-move", args={"data-d": "-1"},
       why="This shot is already first."),
    _c("timeline.move-right", "Move the shot later", "timeline",
       "studio-move", args={"data-d": "1"},
       why="This shot is already last."),
    _c("timeline.zoom-in", "Zoom in", "timeline", "studio-zoom",
       args={"data-z": "1"}, keys=("+", "=")),
    _c("timeline.zoom-out", "Zoom out", "timeline", "studio-zoom",
       args={"data-z": "-1"}, keys=("-", "_")),
    _c("timeline.zoom-fit", "Fit the whole reel on screen", "timeline",
       "studio-zoom", args={"data-z": "0"}, keys=("0",)),
    _c("timeline.undo", "Undo the last edit", "timeline", "studio-undo",
       keys=("Ctrl+Z",), why="There is nothing to undo."),
    _c("timeline.redo", "Put back what you undid", "timeline", "studio-redo",
       keys=("Ctrl+Shift+Z",), why="There is nothing to put back."),
    _c("timeline.history", "Everything you have done to this reel", "timeline",
       "studio-hist"),
    _c("timeline.tool-select", "Select tool — move a shot, drag its edge to trim",
       "timeline", "studio-tool", args={"data-tool": "select"}, keys=("V",)),
    _c("timeline.tool-roll", "Roll tool — move the join, keep the reel's length",
       "timeline", "studio-tool", args={"data-tool": "roll"}, keys=("N",)),
    _c("timeline.tool-razor", "Razor tool — cut a shot in two",
       "timeline", "studio-tool", args={"data-tool": "razor"}, keys=("C",)),
    _c("timeline.shuttle-back", "Shuttle backwards", "timeline", None, keys=("J",)),
    _c("timeline.shuttle-stop", "Stop", "timeline", None, keys=("K",)),
    _c("timeline.shuttle-on", "Shuttle forwards, faster each press", "timeline",
       None, keys=("L",)),
    _c("timeline.in-point", "Mark the start of the stretch to watch", "timeline",
       "studio-in", keys=("I",)),
    _c("timeline.out-point", "Mark the end of it", "timeline", "studio-out",
       keys=("O",)),
    _c("timeline.io-clear", "Forget the in and out points", "timeline",
       "studio-io-clear"),
    _c("timeline.mark", "Drop a mark at the playhead", "timeline", "studio-mark",
       keys=("M",)),
    _c("timeline.mark-clear", "Take every mark off", "timeline",
       "studio-mark-clear"),
    _c("timeline.mark-go", "Go to a mark", "timeline", "studio-mark-go",
       palette=False),
    _c("timeline.history-back", "Go back to a step", "timeline",
       "studio-hist-back", palette=False),
    _c("timeline.history-forward", "Go forward to a step", "timeline",
       "studio-hist-fwd", palette=False),
    _c("timeline.render", "Render the reel", "timeline", "studio-render"),
    _c("timeline.export", "Write this reel out as a timeline (OpenTimelineIO)",
       "timeline", "studio-export", args={"data-kind": "otio"}),
    _c("timeline.export-premiere", "Write it out for Premiere (FCP7 XML)",
       "timeline", "studio-export", args={"data-kind": "fcp7"}),
    _c("timeline.cancel", "Stop the render", "timeline", "studio-cancel",
       why="Nothing is rendering."),
    _c("timeline.show", "Show the finished file", "timeline", "studio-show",
       why="There is no rendered file yet."),
    _c("timeline.mute", "Mute the preview", "timeline", "studio-pv-mute"),
    _c("timeline.fullscreen", "Play the preview full screen", "timeline",
       "studio-pv-full"),
    _c("timeline.slip", "Nudge where the kill sits", "timeline", "studio-slip",
       palette=False),
    _c("timeline.cut", "Show more or less before or after a kill", "timeline",
       "studio-cut", palette=False),
    _c("timeline.offset", "Move the song against the cuts", "timeline",
       "studio-offset", palette=False),
    _c("timeline.seek", "Seek on the timeline", "timeline", "studio-seek",
       palette=False),
    _c("timeline.select", "Select a shot", "timeline", "studio-select",
       palette=False),
    _c("timeline.mix", "Mix the kill effects", "timeline", "studio-mix",
       palette=False),
    _c("timeline.restyle", "Rebuild with another look", "timeline",
       "studio-restyle"),
    _c("timeline.transition-all", "Use this transition on every cut",
       "timeline", "studio-tr-all"),
    _c("timeline.effects-all", "Use these effects on every shot", "timeline",
       "studio-fx-all"),
    _c("timeline.camera-source", "Where the camera comes from", "timeline",
       "studio-cam-src", palette=False),
    _c("timeline.lyrics-shift", "Shift the words earlier or later", "timeline",
       "studio-lyr-shift", palette=False),
    _c("timeline.lyrics-move", "Move the words on the picture", "timeline",
       "studio-lyr-move"),
    _c("timeline.lyrics-boxes", "Draw the boxes the words go in", "timeline",
       "studio-lyrbox-mode"),
    _c("timeline.lyrics-box-add", "Add another box for the words", "timeline",
       "studio-lyrbox-add"),
    _c("timeline.lyrics-box-clear", "Clear the boxes", "timeline",
       "studio-lyrbox-clear"),
    _c("timeline.lyrics-reset", "Put the words back where the look has them",
       "timeline", "studio-lyr-pos-reset"),
    _c("timeline.edit-song", "Edit the song and mark the kills", "timeline",
       "studio-edit-song"),
    _c("timeline.song", "Choose a song", "timeline", "studio-song"),
    _c("timeline.no-song", "Make the reel without a song", "timeline",
       "studio-nosong"),

    # -- the song pane -----------------------------------------------------
    _c("song.play", "Play the part", "song", "studio-sg-play", keys=("Space",)),
    _c("song.mark", "Mark a kill here", "song", "studio-sg-mark", keys=("K",)),
    _c("song.unmark", "Undo the last mark", "song", "studio-sg-unmark",
       why="There is no mark to undo."),
    _c("song.mark-drop", "Remove the chosen mark", "song",
       "studio-sg-markdrop", palette=False),
    _c("song.mark-nudge", "Nudge the chosen mark", "song",
       "studio-sg-marknudge", palette=False),
    _c("song.mark-play", "Hear the chosen mark", "song", "studio-sg-markplay",
       palette=False),
    _c("song.clear-marks", "Clear every mark", "song",
       "studio-sg-clearmarks"),
    _c("song.from-kills", "Put the marks where the kills are now", "song",
       "studio-sg-fromkills"),
    _c("song.apply", "Use this part of the song", "song", "studio-sg-apply"),
    _c("song.at-drop", "Build the reel into the drop", "song",
       "studio-sg-atdrop"),
    _c("song.fit", "Fit the song on screen", "song", "studio-sg-fit"),
    _c("song.snap-bar", "Snap to the nearest bar", "song",
       "studio-sg-snapbar"),
    _c("song.pick", "Choose another song", "song", "studio-sg-pick"),
    _c("song.none", "Take the song off", "song", "studio-sg-none"),
    _c("song.lane", "Show another lane", "song", "studio-sg-lane",
       palette=False),
    _c("song.nudge", "Nudge the part", "song", "studio-sg-nudge",
       palette=False),
    _c("song.window", "How much of the song to show", "song",
       "studio-sg-win", palette=False),
    _c("song.song", "Pick this song", "song", "studio-sg-song",
       palette=False),

    # -- importing a clip --------------------------------------------------
    _c("import.play", "Play the clip", "import", "studio-imp-play",
       keys=("Space",)),
    _c("import.mark", "Mark a kill here", "import", "studio-imp-mark",
       keys=("K",)),
    _c("import.prev-frame", "Back one frame", "import", "studio-imp-prev",
       keys=(",",)),
    _c("import.next-frame", "On one frame", "import", "studio-imp-next",
       keys=(".",)),
    _c("import.step", "Jump a second", "import", "studio-imp-step",
       palette=False),
    _c("import.seek", "Go to a marked kill", "import", "studio-imp-seek",
       palette=False),
    _c("import.drop", "Remove a mark", "import", "studio-imp-drop",
       palette=False),
    _c("import.clear", "Clear every mark", "import", "studio-imp-clear"),
    _c("import.cut", "Remove the trimmed part", "import", "studio-imp-cut"),
    _c("import.cut-from", "Trim from here", "import", "studio-imp-cutfrom"),
    _c("import.cut-to", "Trim to here", "import", "studio-imp-cutto"),
    _c("import.cut-clear", "Keep the whole clip", "import",
       "studio-imp-cutclear"),
    _c("import.detect", "Find the kills in this clip", "import",
       "studio-imp-detect"),
    _c("import.detect-all", "Find the kills in all of them", "import",
       "studio-imp-detectall"),
    _c("import.preset", "Use a profile", "import", "studio-imp-preset",
       palette=False),
    _c("import.save", "Save the marks", "import", "studio-imp-save"),
    _c("import.close", "Leave the importer", "import", "studio-imp-close",
       keys=("Escape",)),
    _c("import.edit", "Mark the kills in this clip", "import",
       "studio-imp-edit", palette=False),

    # -- the effect picker -------------------------------------------------
    _c("picker.open", "Choose an effect", "picker", "studio-fxp-open",
       palette=False),
    _c("picker.pick", "Use this one", "picker", "studio-fxp-pick",
       palette=False),
    _c("picker.versions", "Show every version of this effect", "picker",
       "studio-fxp-group", palette=False),
    _c("timeline.lock", "Lock the picked shots together, or unlock them", "timeline",
       "studio-lock"),
    _c("timeline.jump-section", "Jump to a section of the inspector", "timeline",
       "studio-insp-jump", palette=False),
    _c("picker.stage", "Use the one being shown", "picker",
       "studio-fxp-stage", keys=("Enter",)),
    _c("picker.clear", "Clear them all", "picker", "studio-fxp-clear"),
    _c("picker.drop", "Take this one off", "picker", "studio-fxp-drop",
       palette=False),
    _c("picker.done", "Done — keep what was clicked", "picker",
       "studio-fxp-done"),
    _c("picker.cancel", "Close the picker", "picker", "studio-fxp-cancel",
       keys=("Escape",)),

    # -- making a reel -----------------------------------------------------
    _c("make.open", "Make a reel from the clips picked", "make",
       "studio-make", why="Pick some clips first."),
    _c("make.build", "Build and render it", "make", "studio-build"),
    _c("make.cancel", "Close without making one", "make", "studio-make-cancel"),
    _c("make.format", "Portrait or landscape", "make", "studio-fmt",
       palette=False),
    _c("make.fit", "How the picture fills a vertical frame", "make",
       "studio-mk-fit", palette=False),
    _c("make.mode", "Choose the part of the song", "make", "studio-mk-mode",
       palette=False),
    _c("make.preset", "Start from the drums", "make", "studio-mk-preset",
       palette=False),
    _c("make.play", "Play the part", "make", "studio-mk-play"),
    _c("make.nudge", "Nudge the part a bar", "make", "studio-mk-nudge",
       palette=False),
    _c("make.skip", "Skip through the song", "make", "studio-mk-skip",
       palette=False),
    _c("make.restart", "Back to the start of the song", "make",
       "studio-mk-restart"),
    _c("make.choose-effect", "Choose an effect for a slot from a list", "make",
       "studio-hand-pick", palette=False),
    _c("make.set-weight", "Draw an effect more or less often", "make",
       "studio-set-weight", palette=False),
    _c("make.set-remove", "Take an effect out of a slot", "make",
       "studio-set-remove", palette=False),
    _c("make.jump", "Jump to a section of the Make page", "make",
       "studio-mk-jump", palette=False),
    _c("make.plan-kills", "Show where the kills will land on the song", "make",
       "studio-mk-plan"),
    _c("make.mark-kill", "Mark a kill at the playhead", "make",
       "studio-mk-addmark"),
    _c("make.clear-marks", "Put the kills back to automatic", "make",
       "studio-mk-clearmarks"),
    _c("make.del-mark", "Remove one kill mark", "make",
       "studio-mk-delmark", palette=False),
    _c("make.nudge-mark", "Nudge one kill mark a tenth of a second", "make",
       "studio-mk-nudgemark", palette=False),
    _c("make.mark-drop", "Mark a bass drop at the playhead", "make",
       "studio-mk-adddrop", keys=("D",)),
    _c("make.clear-drops", "Put the drops back to the ones AutoStream found", "make",
       "studio-mk-cleardrops"),
    _c("make.del-selected", "Delete the selected kill and drop marks", "make",
       "studio-mk-delsel", keys=("Delete",), why="No mark is selected."),
    _c("make.select-all-marks", "Select every kill and drop mark", "make",
       "studio-mk-selall"),
    _c("make.select-no-marks", "Clear the selection of marks", "make",
       "studio-mk-selnone", palette=False),
    _c("make.pick-mark", "Select one mark", "make",
       "studio-mk-pick", palette=False),
    _c("make.samples", "Show every style on my own kills", "make",
       "studio-samples-start"),
    _c("make.samples-stop", "Stop cutting the style samples", "make",
       "studio-samples-stop", palette=False),

    # -- the opening clip --------------------------------------------------
    _c("intro.open", "Add or edit the opening clip", "intro",
       "studio-intro-open"),
    _c("intro.add", "Add a GIF or video to open with", "intro",
       "studio-intro-add"),
    _c("intro.pick", "Use this opener", "intro", "studio-intro-pick",
       palette=False),
    _c("intro.play", "Play the part", "intro", "studio-intro-play"),
    _c("intro.here", "Start the opener here", "intro", "studio-intro-here"),
    _c("intro.whole", "Use the whole clip", "intro", "studio-intro-whole"),
    _c("intro.nudge", "Nudge where it starts", "intro", "studio-intro-nudge",
       palette=False),
    _c("intro.fit", "How it fills the frame", "intro", "studio-intro-fit",
       palette=False),
    _c("intro.fit-lead", "Fill the lead-in", "intro",
       "studio-intro-fit-lead", palette=False),
    _c("intro.use", "Use this opener", "intro", "studio-intro-use"),
    _c("intro.clear", "Open without one", "intro", "studio-intro-clear"),
    _c("intro.off", "Take the opener off", "intro", "studio-intro-off"),
    _c("intro.delete", "Delete this opener for good", "intro",
       "studio-intro-del", palette=False),
    _c("intro.cancel", "Close the opener chooser", "intro",
       "studio-intro-cancel"),

    # -- your camera -------------------------------------------------------
    _c("facecam.attach", "Attach a camera video", "facecam",
       "studio-fc-attach"),
    _c("facecam.unlink", "Take the camera video off", "facecam",
       "studio-fc-unlink", palette=False),
    _c("facecam.lineup", "Line the camera up", "facecam", "studio-fc-lineup",
       palette=False),
    _c("facecam.play", "Play both together", "facecam", "studio-fc-play"),
    _c("facecam.sync", "Find the offset from the sound", "facecam",
       "studio-fc-sync"),
    _c("facecam.nudge", "Nudge the camera offset", "facecam",
       "studio-fc-nudge", palette=False),
    _c("facecam.frame", "Another frame to draw on", "facecam",
       "studio-fc-frame", palette=False),
    _c("facecam.box-reset", "Draw the box again", "facecam",
       "studio-fc-boxreset"),

    # -- looks and the drawers ---------------------------------------------
    _c("looks.deal", "Deal another template", "looks", "studio-deal"),
    _c("looks.deal-reset", "Back to the look's own", "looks",
       "studio-deal-reset"),
    _c("looks.build-examples", "Cut the missing examples", "looks",
       "studio-bin-build"),
    _c("looks.stop-examples", "Stop cutting examples", "looks",
       "studio-bin-stop"),
    _c("looks.favourites-only", "Show only the parts kept", "looks",
       "studio-bin-favonly"),
    _c("looks.favourite-part", "Keep this part", "looks", "studio-bin-fav",
       palette=False),
    _c("looks.versions", "Show every version of this effect", "looks",
       "studio-bin-group", palette=False),
    _c("looks.slot", "Open a drawer", "looks", "studio-bin-slot",
       palette=False),
    _c("looks.style", "Choose a look", "looks", "studio-style",
       palette=False),
    _c("looks.arrange", "Choose the order of the clips", "looks",
       "studio-arrange", palette=False),
    _c("looks.shape", "Shape the reel", "looks", "studio-shape",
       palette=False),
    _c("looks.shape-reset", "Back to the look's own shaping", "looks",
       "studio-shape-reset"),
    _c("looks.fill", "How long the reel runs", "looks", "studio-fill",
       palette=False),
    _c("looks.pin", "Pin this part into the template", "looks", "studio-pin",
       palette=False),

    # -- clips and reels ---------------------------------------------------
    _c("library.pick", "Pick a clip", "library", "studio-pick",
       palette=False),
    _c("library.folder", "Select or unselect a run", "library",
       "studio-folder", palette=False),
    _c("library.match", "Select or unselect a match", "library",
       "studio-match", palette=False),
    _c("library.game", "Open a folder", "library", "studio-game",
       palette=False),
    _c("library.open-folder", "Open this folder", "library",
       "studio-open-folder", palette=False),
    _c("library.open-run", "Open this run", "library", "studio-open-run",
       palette=False),
    _c("library.crumb", "Go back up the library", "library", "studio-crumb",
       palette=False),
    _c("library.only-picked", "Show only the clips picked", "library",
       "studio-only-picked"),
    _c("library.clear", "Unpick every clip", "library", "studio-clear",
       why="Nothing is picked."),
    _c("library.favourite", "Keep this clip", "library", "studio-fav",
       palette=False),
    _c("library.favourite-picked", "Keep the clips picked", "library",
       "studio-fav-selected", why="Nothing is picked."),
    _c("library.preview", "Watch this clip", "library", "studio-preview",
       palette=False),
    _c("library.preview-close", "Close the clip", "library",
       "studio-preview-close", palette=False),
    _c("library.add", "Add clips to the reel on the timeline", "library",
       "studio-add"),
    _c("library.add-cancel", "Stop adding clips", "library",
       "studio-add-cancel", palette=False),
    _c("library.import", "Add your own clip", "library", "studio-imp-add"),
    _c("library.youtube", "Paste a YouTube link", "library", "studio-yt"),
    _c("library.youtube-go", "Download it", "library", "studio-yt-go"),
    _c("library.youtube-close", "Close the link box", "library",
       "studio-yt-close"),
    _c("library.delete", "Delete the clips picked", "library",
       "studio-delete", why="Nothing is picked."),
    _c("library.delete-go", "Delete them", "library", "studio-del-go",
       palette=False),
    _c("library.delete-cancel", "Keep them", "library", "studio-del-cancel",
       palette=False),
    _c("library.open-reel", "Open this reel on the timeline", "library",
       "studio-open", palette=False),
    _c("library.watch-reel", "Watch this reel", "library", "studio-watch",
       palette=False),
    _c("library.reel-format", "Show only one shape of reel", "library",
       "studio-reel-fmt", palette=False),
    _c("library.reels-more", "Show more reels", "library",
       "studio-reels-more"),
    _c("library.reel-delete", "Delete this reel", "library",
       "studio-reel-del", palette=False),
    _c("library.reel-delete-go", "Delete it", "library", "studio-rdel-go",
       palette=False),
    _c("library.reel-delete-cancel", "Keep it", "library",
       "studio-rdel-cancel", palette=False),
]


# ------------------------------------------------------------------ helpers

def ids() -> set[str]:
    return {c["id"] for c in COMMANDS}


def by_id(cid: str) -> dict | None:
    """One command by name, or None. The browser tier and the tests both ask."""
    for c in COMMANDS:
        if c["id"] == cid:
            return c
    return None


def acts() -> set[str]:
    """Every `data-act` the registry stands on."""
    return {c["act"] for c in COMMANDS if c["act"]}


def bindings() -> list[tuple[str, str, str]]:
    """(scope, key, command id) for every binding declared."""
    return [(c["scope"], k, c["id"]) for c in COMMANDS for k in c["keys"]]


def payload() -> dict:
    """What /api/studio/commands answers and the page is built from."""
    return {"ok": True, "scopes": list(SCOPES), "commands": COMMANDS}


COMMANDS_JS: str = (
    "/* The command registry, from autostream/ui/commands.py. The page renders\n"
    "   the palette and the key sheet from this and nothing else, so a command\n"
    "   added there appears in both without being typed twice. */\n"
    "const STUDIO_SCOPES = " + json.dumps(list(SCOPES), ensure_ascii=False) + ";\n"
    "const STUDIO_CMDS = " + json.dumps(COMMANDS, ensure_ascii=False) + ";\n"
)

__all__ = ["COMMANDS", "COMMANDS_JS", "SCOPES", "SCOPE_IDS", "acts",
           "bindings", "by_id", "ids", "payload"]
