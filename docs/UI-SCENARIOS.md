# UI test scenarios

Every screen AutoStream has, what a person does on it, and what must be true
afterwards. This is the catalogue the Playwright tiers are written from; a
scenario here with no test against it is a known gap, and the gaps are marked
rather than left to be discovered.

**How to run any of this: see [TESTING-UI.md](TESTING-UI.md).**

## What the surface actually is

Counted from the source rather than estimated — `surface.ui_actions()` and
`surface.ui_operable_ids()` enumerate them, and `tests/verify/test_surface.py`
fails if one appears that nothing accounts for.

Re-counted 2026-10-11, when the Studio library became a drill-down. The
numbers below are what the two helpers print today; the ones they replace
(190 controls, studio 121) were a year of features out of date, which is how
a measured figure quietly becomes an estimate.

| Page | `data-act` controls | Operable ids |
|---|---|---|
| studio | 165 | 17 |
| clips | 47 | 10 |
| reel | 22 | 2 |
| settings | 7 | 10 |
| setup | 2 | 1 |
| dashboard | 2 | 12 |
| logs | 0 | 3 |
| shell | 0 | 2 |
| **total** | **244** | **57** |

Dashboard, logs and shell carry no `data-act`: they are wired by element id,
which is why both columns matter.

## How the tiers divide the work

Writing 244 hand-written cases would produce 244 things to keep current, most
asserting only "it did not explode". So the work is split:

- **The sweep** (`test_ui_sweep.py`) presses *everything*, mechanically, and
  asserts the weak-but-universal property: no console error, no uncaught
  exception, no request the page made coming back refused. This is what gives
  literal every-button coverage, and it cannot drift, because it reads the
  control list out of the source each run.
- **The journey** (`test_ui_journey.py`) walks one person's whole path from a
  blank install to finished clips, in order, asserting the real outcome at
  each step.
- **Focused files** assert the specific things that have gone wrong before and
  the things a sweep cannot see — that a video really plays, that a saved file
  really appears, that a stage really is locked.

A sweep passing means nothing is broken in a way that shouts. A focused test
passing means a feature works. Both are needed; neither substitutes.

---

# 1 · Setup — a blank install

`tests/verify/test_ui_setup.py`

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 1.1 | Open the app with no config at all | The first screen renders, is legible, and names what it wants | yes |
| 1.2 | The wizard's steps advance | Each step reachable, none dead-ends | **gap** |
| 1.3 | Finish with clips only, no streaming | Lands on a usable app with streaming off | **gap** |
| 1.4 | Google sign-in is offered but refusable | Skipping leaves a working clips-only install | **gap** |

Setup is the least covered area and the first thing a new user meets. The
wizard talks to Google and OBS, which is why it is hard — the scenarios are
listed so the gap is visible.

# 2 · Shell — the frame around every page

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 2.1 | Each of the six pages opens | Renders, nothing in the console | yes |
| 2.2 | Switching pages repeatedly | No leak of one page's state into another | sweep |
| 2.3 | A wrong `?k=` token | The wrong-key page, not a stack trace | **gap** |
| 2.4 | The status poll with the engine idle | No refused requests over a minute | yes |

# 3 · Dashboard

11 operable ids, no `data-act`.

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 3.1 | Open while IDLE | Phase shown, nothing claims to be live | sweep |
| 3.2 | Go live / stop buttons exist and are wired | Press does not error; state is reported | sweep |
| 3.3 | Chat panel renders and escapes HTML | A `<script>` in a message is text | **gap** |
| 3.4 | Quit asks the engine rather than killing it | `/api/cmd` is what gets called | **gap** |

# 4 · Library

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 4.1 | The app list renders | Rows appear, each with a source | sweep |
| 4.2 | Search narrows the list | Fewer rows, and the right ones | **gap** |
| 4.3 | A game shows a Thumbnail button | Present for anything that will have a broadcast | **gap** |
| 4.4 | A launcher-run game (Valorant) shows it too | `stream=false` must not hide it — this was the bug | **gap** |
| 4.5 | A non-game (Command Prompt) does not | No thumbnail button on Character Map | **gap** |
| 4.6 | Assigning a thumbnail saves under the exe | `games.yaml` keyed on the exe, not the catalogue key | **gap** |

4.4 and 4.6 are the two that have actually broken. They need a test.

# 5 · Clips — the six stages

`tests/verify/test_ui_clip_stages.py` (12 tests)

## 5a · Pick a video

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 5.1 | The stream list renders | Rows, newest first | yes |
| 5.2 | More than 12 streams | Pager appears, 12 to a page | yes |
| 5.3 | Page two | Rows keep their index into the whole list | yes |
| 5.4 | Filter by game | Resets to page one | **gap** |
| 5.5 | Pick a stream | Advances to Choose the part | yes |
| 5.6 | Pick a local file | Advances, and the file is registered to play | partial |
| 5.7 | A stream whose recording is gone | Marked, and cannot be cut | **gap** |
| 5.8 | Remove gone streams from the list | Journal changes, video untouched | **gap** |

## 5b · Choose the part

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 5.9 | A seekable recording | Plays whole, duration is the real one | yes |
| 5.10 | A fragmented or non-web format | Falls back, and says why | **gap** |
| 5.11 | Mark start/end from the playhead | The window follows the video | yes |
| 5.12 | Drag the handles | Window updates, strip dims outside it | **gap** |
| 5.13 | Whole video | Resets to no window | **gap** |
| 5.14 | Save this part | A real file appears on disk | yes |

## 5c · How to read it (Counter-Strike only)

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 5.15 | Three readers offered | Each with its measured cost | **gap** |
| 5.16 | Choosing the tally opens calibration | The card box panel appears | **gap** |
| 5.17 | A non-CS2 game | The stage is absent, not empty | yes |

## 5d · Style

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 5.18 | The fold starts shut and is summarised | Summary names the current settings | yes |
| 5.19 | Every segmented control marks its choice | Exactly one `is-active` | yes |
| 5.20 | Clip length only in Custom | Hidden otherwise, by design | yes |
| 5.21 | Make clips runs | A job starts and the loader appears | **gap** |
| 5.22 | Review clips first | Opens the review stage with rows | **gap** |

## 5e · Review

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 5.23 | Locked before a run | Unreachable with nothing in it | yes |
| 5.24 | Captions and voice lines per clip | Edits persist to the cut | **gap** |
| 5.25 | The montage toggle here overrides Style | The run body carries this answer | **gap** |
| 5.26 | Voices listed when installed | Not "no voices installed" with 28 loaded | **gap** |
| 5.27 | The download button when they are absent | Offered, and only when it would help | **gap** |

## 5f · Clips (results)

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 5.28 | Locked before a run | Unreachable | yes |
| 5.29 | A clip plays in the page | Real media, real duration | yes |
| 5.30 | Framing marks its choice | The reported bug | yes |
| 5.31 | Upload to YouTube | Refused safely with no account | **gap** |

# 6 · Studio — 165 controls

`test_ui_playwright.py` covers the two big flows and the effect picker.

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 6.1 | A reel is made, edited and re-rendered | A file comes out both times | yes |
| 6.2 | Effects, restyle, cut to marked kills | The render reflects the edits | yes |
| 6.3 | Clips tab: pick, range-pick, clear | Selection count follows | sweep |
| 6.4 | Timeline: zoom, snap, undo | No console error; undo restores | sweep |
| 6.5 | Song tab: pick a song, see the beats | The beat grid is drawn | **gap** |
| 6.6 | Song tab: drag the part | Snaps to a beat | **gap** |
| 6.7 | Facecam: draw a box, keep it | Box persists across reels | **gap** |
| 6.8 | Every drawer of the parts bin deals | No dead drawer | sweep |
| 6.9 | The effect picker: search by name and by code, preview follows the pointer, Esc closes and returns focus, a click applies undoably, recently used comes first, several at once with Done, a chip's × takes one off | The project changes exactly as chosen | yes |
| 6.10 | Lyrics: with a .lrc beside the song, choose a look and a typeface, the LYRICS stand-in hidden until "Move on the picture", drag it, pick one of nine places, move the timing +0.5 s, render (stand-in gone) | The reel is saved with the look, face and place, and the Lyrics group says where the words came from | yes (inside 6.2) |
| 6.11 | Your reels: more than eight fold to two rows; unfold, search, filter by shape, sort | Every reel is reachable, typing keeps focus, each card shows a real still | yes |
| 6.12 | Headshots: Valorant clips with a reading show "· N HS"; Make offers "Headshot kills only" with what it keeps; ticked, the plan uses only headshot kills | Only headshot kills are in the project | yes |
| 6.13 | The change count after a render: the vignette on (1), off again (0, the button stops saying Apply), two reel settings changed and one undone (1), a shot's speed changed and put back by hand (0) | The count is what differs from the video, never how many clicks it took | yes |
| 6.14 | How long: "Fill the song part I picked" is greyed until a song and a part are chosen, then lit by default; "Every clip I chose" says what it does; Keep every kill ticked; Best order chosen; Build | The plan request carries the part, `fill`, `keep_all` and `arrange: hits`, the project keeps all four, and the reel fills most of the part | yes (`test_ui_studio_length`) |
| 6.15 | Rebuild with another style on a reel cut to a part | The new plan is asked for on the same part, with the same How long and Keep every kill | yes (`test_ui_studio_length`) |
| 6.16 | Song tab: lengthen the part well past the reel and "Use this part" | The reel is planned again to fill it, the part is kept on the project, and the tab reopens on it rather than on the reel's length | yes (`test_ui_studio_length`) |
| 6.17 | Instant preview: delete a shot from a rendered reel; play across the new cut; a song applied plays under it | The player takes the edit in the same frame (shots, length, the clip after the cut) with nothing rendered; its clip/second/rate at 30 reel times equal `preview_at()`'s; the cut lands within 50 ms; the song is within 0.2 s of the cuts | yes |
| 6.18 | Background render: stop editing; then edit again while a Render you pressed is running | It starts itself after the idle delay and the player changes over to a file as long as the edited timeline; never a background request while your render runs; the edit made during it renders itself afterwards | yes |
| 6.19 | Perfect fit: the arrangement says it is slower, the Make dialog warns it takes up to ~30 s, and the plan has every kill of a triple, a double and a single, each shot's kill within a frame of its hit; a rebuild in another style keeps the arrangement | Every chosen kill is in the timeline; `arrange` is still `fit` after a restyle | yes |
| 6.20 | The preview has its own play bar: from an edit until the render catches up, play and pause from the bar and from the picture, seek to three quarters, mute, fullscreen, the app's volume and speed | The bar is on screen while paused and hovered and out of the way while playing; the seek lands on the shot `studio_pvAt` has there; mute silences clip and song; volume and 2x reach the preview; fullscreen takes `#studio-player` | yes |
| 6.21 | Instant preview with lyrics: a look chosen, then another, before any render | The render's own words are over the preview within seconds, on its clock, transparent where nothing is sung; a new look brings a new overlay without a render | yes |
| 6.22 | Instant preview of a 9:16 reel with Fit the whole picture | The picture sits over a blurred copy of itself, not black bands; the lyrics are redrawn for the new shape | yes |
| 6.23 | The effect picker: point at an option | It plays on a stage that takes most of the dialog, centred, 16:9, with the list in a column beside it; a sharp 1280-wide copy replaces the card-sized one; the stage's button does what clicking the card does | yes |
| 6.24 | The library opens on folders: one card per game plus Favourites, each saying how many clips and runs; open one and its runs are listed, newest first, with a chip per match in them; a run with no match record shows no chips | No clip tile is rendered before a folder is opened, and a folder opens on runs rather than straight onto clips | yes (`test_ui_studio_folders`) |
| 6.25 | A run opens on its clips, grouped by the match each was cut from: the map, the mode, the score coloured by the result, the player's K/D/A and where the match starts in the recording; clips outside every match get their own group; Select match takes that match and nothing else; Select run still takes the sitting | Every clip in the run is on screen exactly once, under its own match; the selection is the clips of the group pressed | yes (`test_ui_studio_folders`) |
| 6.26 | Getting back out: the crumbs walk a run up to its folder and a folder up to the grid; where you are survives the pane being rebuilt; a search typed at the folders finds a clip two levels down, and clearing it puts you back where you were | A drill-down takes nothing away: the search still answers from the whole library, and no level is a one-way door | yes (`test_ui_studio_folders`) |
| 6.27 | The effect picker on a single choice (an ending, a speed): click one, then another, then Done | Each click applies straight away and the dialog stays up, with the tick and the stage button on what is in use; Done closes it keeping the last one, and Cancel closes it putting back the one that was there when it opened | yes (inside 6.9 and 6.23) |
| 6.28 | The order of a reel: open Make, see six arrangements with what each does, Best order marked recommended and Perfect fit carrying its ~30 s cost; press one, then press another in the strip at the foot of the Clips tab | The dialog and the strip are one choice: pressing either shows in both, the plan request carries `arrange`, and the old As chosen / Most kills first / Oldest first row is gone | yes (`test_ui_studio_order`) |
| 6.29 | Where the picked clips are: pick from two runs and read the folder card, the run rows and the match headings; turn on "Show only these"; read the tray | Every level that hides clips behind a click says how many of its clips are picked and nothing when none are; the filter is real, so `studio_visible()` agrees with the screen; the tray names the runs | yes (`test_ui_studio_folders`) |
| 6.30 | Adding to a reel: press Add clips, then read the band | It names the reel, counts what is in it, carries a chip per run those clips came from, and each chip opens that run | yes (`test_ui_studio_folders`) |
| 6.31 | The Make page: open it, see it as a page (not an overlay) with a section nav; open an effect slot to a list, add a second effect, weight it; place a song and read the kills drawn on it, move one, delete one, go back to automatic; press Show every style on my kills | The page replaces the Studio view; a set sends each id as often as its weight; `marks` reach Build only once one is touched; a card's video is a sample cut from the same clips | yes (`test_ui_studio_make_page`) |
| 6.31 | Three tabs, three jobs: Clips, Reels, Looks | The clips tab holds only clips (no reels grid, no drawers, no 223-trillion counter); the reels tab draws the grid, or says what to do when there are none; the looks tab holds the drawers and the counter; moving between them says nothing in the console | yes (`test_ui_studio_folders`) |
| 6.32 | Lyrics: with a look and a typeface chosen, pick **How they arrive** — one word, a whole line, the line building up, a typewriter | The choice is kept on the reel and named in the change list; the preview redraws without a render; the look's own reveal draws exactly what it drew before the setting existed | yes (inside 6.2) |
| 6.33 | Lyrics: set **Width**, **Size** and **Opacity** | Each is one edit in the change list and one press of undo; a narrower box wraps the words and brings the type down; the full box at full size and solid draws exactly what the look drew before the settings existed | yes (inside 6.2) |
| 6.34 | Every action by name: press Ctrl+K from the Clips tab and from the timeline, type "ripp", move with the arrows, run one with Enter | The list opens over whatever pane is showing, the scope you are in is listed first, each row carries its key, Enter runs the same thing its button runs, and Esc closes it leaving the project untouched | **gap** |
| 6.35 | A command that cannot run says why: with a one-shot reel, find "Remove the selected shot" in the list | It is listed, not hidden, and reads "A reel keeps at least one shot, and this is the last one"; pressing Delete says the same thing rather than doing nothing in silence | **gap** |
| 6.36 | The key sheet on **?**: press ? on the timeline, and from the list's "All the keys" | Every scope with a key is a section, in the order the page reads them; each key printed is one the page answers to; typing ? into a text field types a question mark instead of opening it | **gap** |
| 6.37 | The browser tier asks the editor what it can do: GET `/api/studio/commands`, then run each timeline command named there | Every command either runs or gives a reason; no command names a control the page does not render | **gap** |
| 6.38 | Every kill of a shot is a diamond: a shot with three kills draws its own diamond plus two more, smaller and hollow | The shot's own kill still reads as the one the cut is built around | yes |
| 6.39 | Drag another kill's diamond onto a beat | It is pinned there, the shot's `pre` and `duration` do not change, and nothing after it moves | yes |
| 6.40 | Pin a second kill, then drag the first again | Two anchors, and re-dragging one moves it rather than pinning it twice | yes |
| 6.41 | Alt-click a pinned diamond | It floats again, as one gesture and undoably | yes |
| 6.42 | The shot's own diamond, dragged | Still moves the cut, and pins nothing -- the old handle keeps its old meaning | yes |
| 6.43 | Drag a shot's LEFT edge right: less before the kill | The shot before takes the time; both kills play where they did; nothing after the two shots moves | yes |
| 6.44 | Drag a shot's RIGHT edge right: more after the kill | The shot after gives the time from its head, so its kill stays put too; the reel keeps its length | yes |
| 6.45 | Shift-drag a right edge | The old trim: this shot changes length and everything after moves | yes |
| 6.46 | Drag a cut past the next shot's kill, or past the footage a clip has | It stops short and a toast says which limit it hit | yes |
| 6.47 | Trim the head of the first shot, with a song | Reel zero moves and the song moves with it, so every kill meets the same moment of the music | yes |
| 6.48 | Inspector "Before the kill" and "After the kill" | Each moves the cut on its side; Run-up and Length are gone | yes |
| 6.38 | Draw the lyric boxes: press "Draw boxes on the picture", drag a rectangle on the preview, drag it to move, a corner to resize, the knob above it to turn | A box appears where it was drawn, wearing the number 1; each drag is ONE line on the change list and one press of undo; the box is held inside the picture by its own half-width | **gap** |
| 6.39 | Several boxes, and the deal: draw a second and a third, then look at the preview | Each box wears its order number; the first line is drawn in box 1, the second in box 2, the third in box 3 and the fourth back in box 1, without a render | **gap** |
| 6.40 | The box decides the size: draw one wide box and one small one | The words in the small box are drawn smaller than those in the wide one, and neither spills outside the rectangle that was drawn | **gap** |
| 6.41 | Width and Size give way: with boxes drawn, open the Lyrics group; then Clear | Width and Size are replaced by a line saying the boxes decide; clearing the boxes brings both controls back with their old values | **gap** |
| 6.42 | Undo is no longer a one-way door: make three edits, press Ctrl+Z twice, then Ctrl+Shift+Z once | The reel goes back two steps and forward one; both buttons name the step they would cross in their tooltip; neither is enabled when there is nothing on its side | **gap** |
| 6.43 | The history panel: press History, read the list, click a step two back, then click one that was undone | Every step is listed with your place marked; undone steps stay listed and clickable; clicking walks to that step and the change list agrees afterwards | **gap** |
| 6.44 | A fresh edit abandons the way forward: undo twice, then make a new edit | Redo goes dead and the undone steps leave the list — they are not a future of this project any more | **gap** |
| 6.45 | Roll: hold Ctrl and drag the edge between two shots | The join moves, the first shot grows by what the second gives up, the reel's total length is unchanged, and every kill after the join stays within a frame of its mark | **gap** |
| 6.46 | Razor: press C, click a shot a third of the way along; then press Escape | It becomes two shots; the kill stays in the half it happened in; neither half is shorter than a beat; the join between them is a hard cut; Escape puts the tool back to Select | **gap** |
| 6.47 | A tool is never a trap: press C, then Escape; press N, drag an edge, release Ctrl mid-drag | Escape returns to Select; a roll begun with Ctrl stays a roll even after Ctrl is let go, so the reel's length does not jump mid-gesture | **gap** |
| 6.48 | J/K/L: press L three times, then J twice, then K | The reel plays at 1x, 2x, 4x then slows back; K stops it dead; the rate is shown beside the clock | **gap** |
| 6.49 | In, out and marks: press I, play on, press O, then M twice at different points | A band is drawn over the ruler between the two points; a mark appears at each spot and clicking one seeks there; the marks are still there after reopening the reel; nothing is sent to a render | **gap** |
| 6.50 | The inspector reads as blocks: select a shot, then the Reel tab | A shot is Footage / Cut in / On the kill / Camera, the reel Music / Words / Look / Start & end / You, each with a header saying what is set and a jump bar reaching each | yes (`test_ui_studio_editor`) |
| 6.51 | The footage bar: drag the box's tail, its head, then the box itself | An edge moves that cut and every kill stays on its beat; the box uses another part of the clip with the shot's length and place unchanged, is pulled onto a kill near the beat (Alt places freely), and stops at the clip's end saying so | yes (`test_ui_studio_editor`) |
| 6.52 | Locked shots: shift-click shots 2-4, Lock, drag shot 1's ending later; then a cut inside the run; then Unlock | The run slides without any shot shortening and the reel grows; a run in the middle is absorbed by the shot after it; a cut inside the run does not move and says why; locking is not listed as a change to the video | yes (`test_ui_studio_editor`) |
| 6.53 | The Make page's style cards, with nothing pressed | Every card plays its own 15 s sample from the moment the page opens (the shipped set, `key=stock`); none says "Not shown yet"; the page takes the window's width rather than a 1180 px column | yes (`test_ui_studio_make_page`) |
| 6.54 | Several kill marks at once: tick two in the list, press Delete selected; tick one, press the Delete key; Shift-drag across the song | The button counts the selection; both go; the key takes the selection only when there is one and nothing is being typed; a box selects every mark it spans | yes (`test_ui_studio_make_page`, the list and the key) |
| 6.55 | A kill marked with K between two beats, then with Snap marks to the beat ticked | The first lands where the playhead was, to the millisecond; the second on the nearest beat | yes (`test_ui_studio_make_page`) |
| 6.56 | AutoStream's kills and yours: plan, then move one | Planned kills are hollow and green, a moved or added one solid in the accent; the list says auto or yours on each | yes (`test_ui_studio_make_page`) |
| 6.57 | Drops: read the drops found on the song's top lane, press D at the playhead, drag one, then Drops back to automatic | Every drop found is a mark, not only the biggest as a line; a placed one is solid; `drops` reaches the plan only once touched, and the reset sends nothing | yes (`test_ui_studio_make_page`) |
| 6.58 | Play the part with marks on it | A tick sounds as the playhead passes each kill and a low thump at each drop; a seek sounds nothing; unticking Sound on each mark silences both | **gap** (sound is not observable from the page) |
| 6.59 | A shot out of a reel cut to its song's hits: remove the first shot (button or Delete), then move one with the arrows or by dragging it | Every shot after the change moves up one hit and its kill stays on a hit; the last hit goes unused; a reel with no hits is not re-timed, and no other edit re-times it | yes (`test_ui_studio_remark`; the re-timing itself offline in `test_studio`) |

| 6.60 | Song tab: the Hits lane on a drum loop with a quiet opening | Every kick, snare and hat is a tick in its own row and the song's parts are named along the top; no kick is drawn in the opening that has none; the lane hides and comes back from its toggle | yes (`test_ui_studio_hits`) |

6.5 is worth a real test: the beat grid was drawn nowhere for a long time and
nothing noticed.

# 7 · Settings

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 7.1 | A saved setting reaches the app | Read back from the API | yes |
| 7.2 | All ~80 fields round-trip | Nothing silently dropped | **gap** (HTTP tier covers it) |
| 7.3 | Bad values are refused, not 500 | A reason, not a stack trace | **gap** (HTTP tier covers it) |
| 7.4 | Theme switch | Applies without reload | sweep |
| 7.5 | Unsaved-changes guard | Leaving warns | **gap** |
| 7.6 | The three answers "Check for updates" can give | Newer release with a package: offered. Newer release with **no** package attached: said out loud, never "up to date". Nothing newer: said out loud too | yes |

# 8 · Logs

| # | Scenario | Must be true | Covered |
|---|---|---|---|
| 8.1 | Rows render and HTML is escaped | A `<b>` in a log line is text | **gap** |
| 8.2 | Level filter | Client-side, no refetch | sweep |
| 8.3 | The timer stops when the page is left | No polling off-page | **gap** |

---

# The honest summary

| | count |
|---|---|
| Scenarios catalogued | 72 |
| Covered by a focused test | 33 |
| Covered only by the sweep | 12 |
| **Known gaps** | **27** |

The gaps are not a to-do list to be cleared blindly. The ones worth writing
next, in order, are the ones where something has already gone wrong or where
breaking it would be silent:

1. **4.4 / 4.6** — the Library thumbnail for launcher-run games, which broke.
2. **5.26 / 5.27** — the voice list and its download, which broke.
3. **5.21 / 5.22** — actually running a job from the Style page; everything
   downstream depends on it and no browser test starts one.
4. **6.5** — the song beat grid, invisible for a long time.
5. **1.2–1.4** — the setup wizard, the first thing a new user meets.


---

# What the sweep reaches, measured

Counted by `test_ui_sweep.py`, which writes `ui-sweep-coverage.json` on every
run. Measurements, not estimates -- and what `REACHED_FLOOR` is set from.

| | count |
|---|---|
| Controls the source declares | 226 |
| Reached by the sweep | **132** |
| Excused, with a reason each | 23 |
| Still unreached | 71 |

It got there in stages, and the stages say what actually unlocks a UI:

| seeded | reached |
|---|---|
| nothing | 43 |
| + every dialog opened | 86 |
| + a song on disk | 99 |
| + a reel project on disk | 111 |
| + a shot selected on the timeline | 117 |
| + the kill marker open on a clip | 122 |
| + a folder and a run opened in the library | **132** |

That last row is not a sweep change. The marker was gated on `imported` until
S2 (2026-10-05), so for a seeded run the dialog could not be opened at all and
its controls were outside the sweep however the states were written. Five
controls were unreachable because of a product gap, not a test one -- which is
the sort of thing a coverage number is for.

## The 73 still out of reach

| group | n | controls |
|---|---|---|
| `reel` | 12 | reel-back reel-fwd reel-play reel-quick-again reel-quick-fix reel-quick-love … |
| `studio-intro` | 8 | studio-intro-fit studio-intro-fit-lead studio-intro-here studio-intro-nudge studio-intro-off studio-intro-play … |
| `one-offs` | 7 | back finish montage setgame songedit upload … |
| `studio-mk` | 7 | studio-mk-fit studio-mk-mode studio-mk-nudge studio-mk-play studio-mk-preset studio-mk-restart … |
| `studio` | 6 | studio-cancel studio-clear studio-make studio-offset studio-style studio-undo |
| `studio-fc` | 6 | studio-fc-attach studio-fc-lineup studio-fc-nudge studio-fc-play studio-fc-sync studio-fc-unlink |
| `studio-imp` | 4 | studio-imp-drop studio-imp-edit studio-imp-preset studio-imp-seek |
| `studio-sg` | 4 | studio-sg-atdrop studio-sg-markdrop studio-sg-marknudge studio-sg-markplay |
| `demo` | 2 | demo-anyway demo-cards |
| `outro` | 2 | outro-none outro-play |
| `studio-bin` | 2 | studio-bin-favonly studio-bin-stop |
| `cal` | 1 | cal-check |
| `cards` | 1 | cards-open |
| `copy` | 1 | copy-chapters |
| `get` | 1 | get-demos |
| `known` | 1 | known-match |
| `mv` | 1 | mv-make |
| `needsdemo` | 1 | needsdemo-get |
| `studio-add` | 1 | studio-add-cancel |
| `studio-fav` | 1 | studio-fav-selected |
| `studio-shape` | 1 | studio-shape-reset |
| `studio-tr` | 1 | studio-tr-all |
| `upload` | 1 | upload-cancel |
| `use` | 1 | use-local |

Three different kinds of thing are in that list, and they do not share an
answer:

1. **Needs a sub-state inside a surface that is already open** -- an intro
   actually chosen, the make dialog in part mode, marks on a song. Reachable
   in principle. Three attempts at forcing them from outside moved the number
   by zero, including one that fixed a real bug in the attempt
   (`studio.intro.list`, which had been written as `.lib`) and still changed
   nothing -- the page builds that state through a flow rather than from a
   variable. These want driving properly, not forcing.
2. **Needs a fixture a sweep cannot provide** -- `back` and `finish` want an
   unconfigured install; `demo-anyway`, `demo-cards`, `get-demos` and
   `needsdemo-get` want a Counter-Strike run that stopped for a missing
   replay; `upload` and `upload-cancel` want a YouTube account. These belong
   in focused tests with their own fixtures and will never be swept.
3. **Deliberately excused** -- native pickers, destructive actions, `quit`.
   Listed in `DESTRUCTIVE` with a reason each, and a drift guard fails if one
   of those names stops existing.

Forcing group 1 into visibility would raise the number and test nothing, so it
has not been done.
