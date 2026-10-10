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

| Page | `data-act` controls | Operable ids |
|---|---|---|
| studio | 121 | 15 |
| clips | 40 | 10 |
| reel | 22 | 2 |
| settings | 6 | 10 |
| setup | 2 | 1 |
| dashboard | 0 | 11 |
| logs | 0 | 3 |
| shell | 0 | 2 |
| **total** | **190** | **54** |

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

# 6 · Studio — 121 controls

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
| Scenarios catalogued | 62 |
| Covered by a focused test | 23 |
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
| Controls the source declares | 195 |
| Reached by the sweep | **122** |
| Excused, with a reason each | 23 |
| Still unreached | 73 |

It got there in stages, and the stages say what actually unlocks a UI:

| seeded | reached |
|---|---|
| nothing | 43 |
| + every dialog opened | 86 |
| + a song on disk | 99 |
| + a reel project on disk | 111 |
| + a shot selected on the timeline | 117 |
| + the kill marker open on a clip | **122** |

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
