# AutoStream UI redesign: design

Status: **approved by the player, 2026-10-29.** Each screen names the sample he
picked from `Desktop\AutoStream-UI-samples\index.html`. Calls made by the designer
rather than the player are marked **Designer's call**; he was shown them and did not
object.

## Intent

AutoStream works, but it looks like a template and reads like a control panel built by
its developer. The redesign gives every page one calm, premium look that a stranger can
understand in their first hour, without making it slower for someone who uses it daily.

The player's words, in the order they came:

- Spends the time in the Studio making reels, on the Dashboard while live, and in Clips
  cutting a video.
- Wants a **new look with the same flows**: the pages keep doing what they do.
- Builds for **a stranger's first hour** first.
- A game or esports feel was tried (three Valorant-inspired directions) and rejected:
  "less Valorant ... more like linear.app, not the colour palette but the overall
  experience in terms of feeling premium".
- **The app opens on the streaming Dashboard.**
- **Live chat matters**: it gets the right half of the live Dashboard.
- Would wince if the new look is **harder to read** or **slower to use**.

## Goals

1. One visual identity across all six pages (Dashboard, Library, Clips, Studio,
   Settings, Logs), plus first-run setup, in a dark and a light version.
2. The Linear qualities, applied with our own palette:
   - quiet greys, hairline borders, small type set tight;
   - colour only when state changes (live, ready, warning, error);
   - a keyboard hint beside every main action;
   - one search box (Ctrl K) that finds and does anything from any page;
   - fast, purposeful motion only in answer to an action.
3. Every page explains itself to a newcomer: empty states say what to do, statuses say
   what is happening in a sentence, and settings use plain words.
4. No page gets slower: no extra clicks on the paths in daily use, and no less on screen
   where density matters (clip lists, the live Dashboard).

## Non-goals

- New features beyond those listed under "New behaviour" below.
- Changing what the engine, detectors or renderers do.
- A UI framework, a build step or a second toolkit. The page stays one served HTML
  document assembled from `autostream/ui/*.py`.
- The reel *output* look (fonts, overlays). That is separate work; see the
  `reel-assets-quality` notes.

## Anti-goals (it fails if...)

- Any text or status is harder to read than today (contrast, size, or colour as the only
  channel).
- A daily path takes more clicks or keystrokes than today.
- It reads as a knockoff of a game's UI, or as a copy of Linear's colours.
- The live Dashboard pulls focus mid-stream with motion or bright colour.

## Constraints (binding, from the repo)

- **The UI contract in `docs/ROADMAP.md` ("The contract, which is binding")** holds:
  no literal colours outside `autostream/theme.py`; tokens name roles; the accent budget
  is four uses; colour is never the only channel; spacing on the 4px grid
  (`--space-*`); focus rings on `:focus-visible` only; one top-level JS scope with
  prefixed names.
- **Tokens stay in `theme.py`**, emitted as CSS custom properties by `webui.page()`.
  The token names (`bg`, `surface`, `border-subtle`, `text-primary`, ...) are kept so
  page modules don't all change at once; the values change.
- **UI is verified in a browser** (`tests/verify -m ui`, `docs/TESTING-UI.md`,
  `AUTOSTREAM_VERIFY_SOURCE=1` while iterating). `REACHED_FLOOR` (132) in
  `tests/verify/test_ui_sweep.py` must not drop; DOM ids and `data-act` hooks that tests
  drive are kept or the tests move with them. `docs/UI-SCENARIOS.md` is updated before
  tests are added.
- Nothing a test runs may open a window (`AUTOSTREAM_NO_DIALOGS=1`, `appd.NO_WINDOW`).
- macOS builds exist (`docs/MACOS.md`): nothing may assume a Windows-only font without
  a fallback.
- Ships through the normal path: one open PR at a time, version bump, CI release, local
  `-NoGate` build. All four phases ship as one PR (decided).

## Visual system (decided)

**Palette.** Our own neutral greys, not Linear's. Dark:

| Role | Value | Use |
|---|---|---|
| ground | `#141519` | sidebar and page behind everything |
| surface | `#191A1F` | main content |
| raised / hover | `#202228` | inputs, selected rows, buttons |
| active | `#2A2C33` | pressed and segmented-control "on" |
| border | white at 7% / 12% | hairlines / control edges |
| text | `#ECEDEF`, `#A0A3AB`, `#868A93` | primary, secondary, tertiary |
| live / danger | `#F2626A` | the live dot, End stream, destructive actions, errors |
| ready | `#5CC8A8` | done, ready, a first-time chatter |
| warning | `#E5B454` | needs attention |
| border-subtle | white at 7% | decorative hairlines: panel edges, row rules |
| border-strong | white at 38% | the edge of every interactive control |

Light inverts it: ground `#F4F4F6`, surface `#FFFFFF`, text `#18191C` / `#55585F` /
`#666A72`, live/danger `#BF2C34`, ready `#167A5C`, warning `#94610F`, border-subtle
black at 8%, border-strong black at 45%.

**Designer's call, after the builder check measured the first draft:** the contract
wins over the samples. The samples' tertiary text and light-mode state colours scored
3.0-4.1:1 and the control edges about 1.4:1, so the values above were nudged until they
pass. Text is at least 4.5:1 on ground, surface and raised, and control borders are at
least 3:1 (measured with the WCAG 2.x formula on 2026-10-29). In practice tertiary text
is a shade lighter in dark mode, and buttons and inputs get a firmer edge than in the
samples. Hairlines stay as faint as shown, because they are decorative. Tertiary text
is never placed on the active fill, where it drops to about 4.0:1.

**No accent hue (Designer's call).** The `accent` token becomes the primary text
colour, so the system is monochrome:

- The primary button is the text colour as a fill: white on dark, black on light.
- Selection is shown by fill plus a 2px text-colour bar.
- Focus is a 2px ring in the text colour, offset 2px.
- Links are secondary text, underlined.

Colour appears only for state: live and danger red, ready green, warning amber. Red
therefore means "live" or "this destroys or failed", never decoration. The four accent
uses the contract counts are the sidebar selection bar, the settings-nav selection bar,
the primary button and the focus ring.

**Themes.** Five themes (midnight, carbon, ember, forest, daylight) become **System,
Dark, Light**. System follows Windows. Existing configs migrate: `daylight` maps to
`light`, the other four map to `dark`. **Designer's call:** the old theme ids are
accepted on read for one release so a downgrade doesn't break.

**Type.** **Designer's call:** Instrument Sans (SIL OFL) bundled with the app and served
locally by the daemon, with no network request. It falls back to `Segoe UI Variable`,
then `system-ui`. Sizes: 13px base, 12px secondary, 15px section titles, 20px page
titles; slight negative tracking above 15px; tabular figures for every number and
clock. Log lines keep a monospace face because they are log text. No all-caps labels,
no eyebrow labels, no `->` on buttons, no middle-dot meta strings.

**Shape and depth.** 6px radius on controls, 8px on panels, 10px on the window.
Elevation comes from hairline borders, not shadows. The only shadow belongs to overlays
(the Ctrl K palette, menus).

**Icons.** One 16px line set at a 1.5px stroke (`ui/icons.py`), every one paired with
a text label in navigation.

**Motion.** 120-180ms ease-out, only in answer to an action (opening, selecting,
confirming). Honour `prefers-reduced-motion`. Nothing animates on its own while live
except the live dot's halo, which is static.

**Status marks.** Shape and colour together, never colour alone: an empty circle for
not started, a filling circle for working (the pie shows progress), a tick for done,
a dashed ring for needs you, a filled red dot for live.

## Shell (decided)

- **Sidebar (220px):** workspace name, the Ctrl K search box, then Dashboard, Library,
  Clips (with "N new"), Studio, Settings, Logs. **The app's state is pinned at the
  bottom** ("Live, 1:24:07" / "Idle, not recording" / "Recording, 0:12:40"), so it is
  visible from every page. On the Studio the sidebar also lists the games with clip
  counts and Favourites.
- **Top bar (44px):** breadcrumb on the left, page actions on the right, with the
  primary action last and its key shown.
- **The app opens on the Dashboard.**
- **Ctrl K everywhere.** Today's command palette (`ui/commands.py`, Studio only)
  becomes global, with actions from every page. **It also searches clips, reels, games
  and settings by name (agreed).** Results are grouped
  (Clips, Reels, Actions, Settings); Enter runs or opens.
- **Below 900px** the sidebar collapses to icons with labels on hover and focus; the
  Dashboard stacks chat under the status.
- **Quit stays in the sidebar**, under the state line, as today's rail has it
  (Designer's call). There is no tray on macOS.
- **macOS (Designer's call):** `autostream/macos/` belongs to a collaborator and is
  not redesigned here. The shared modules must keep rendering there: where there is no
  engine, the state line is hidden; where a settings group would be empty, it is hidden;
  `macos/features.py` keeps choosing the home page.

## Pages

### Dashboard (decided)

**Live:**
- One status line across the top: the game's thumbnail, "Live on YouTube" with the live
  dot, game and map, the elapsed clock, then Pause (P), Stop recording, End stream
  (danger).
- Below, two equal halves:
  - **Left:** four numbers in a 2x2 (watching now with its 10-minute change, views,
    likes, dropped frames with a plain-words judgement); the watching graph; instant
    replay (Save replay, F9) beside stream health; audio faders.
  - **Stream health shows only what `obs.health()` already reports** (Designer's
    call): skipped and total frames, and congestion. The samples' bitrate and encoder
    load aren't measured today and are not added.
  - **Right, full height: live chat.**
- The session/API-quota card is folded into Logs and the chat hint.

**Live chat** (the player's picks):
- Bigger text (14px) with the time on each message, and a Mod badge on moderators.
- **!clip rows**: a viewer's !clip shows as its own row ("rav3n marked a clip at
  1:23:40"). **While live, the row says "Watch after the stream"** (Designer's call).
  The recording is a fragmented MP4 still being written, with no seek index, and a
  player on the live Dashboard would pull focus. Once the stream ends, the row's
  **Watch** opens that recording in Clips at the mark. No server-side excerpt cutting.
- **First message marker** on someone's first message this stream.
- **"N new messages" pill** when scrolled up; clicking it returns to the bottom.
- `/` focuses the send box; Enter sends. A quiet line says each message costs 50 of the
  day's 10,000 YouTube units.
- No filters (the player declined them).

**Idle, first time:** a heading that says what the app will do ("Start a game and
AutoStream takes it from there"), one paragraph, then a **"Before your first game"**
checklist: OBS found, games found, choose a microphone, going live (optional). Each item
is ticked from real state, and each unticked one has the one button that fixes it.
Beside it, "Where you go live" only when going live is on, otherwise one line saying
it is off and where to turn it on.

**Idle, set up:** "Ready, waiting for a game" with the games that will trigger it,
Start recording now / Go live now, "Since last time" (new clips, finished reels, each
with Open/Watch), audio, and in the chat half a line explaining that chat and !clip
appear once live.

**Replay, match record, platform** keep their behaviour and move into this layout:
the Valorant match-record card shows as a row in the left half when relevant.

### Studio, picking clips

The sidebar lists games and Favourites. The top bar holds the breadcrumb, the
Clips / Reels / Looks switch, Filter, and **Make a reel (R)**. The page opens in
**List** view (**Designer's call**, for speed); **Grid** is one click away and
remembered.

- **List:** rows grouped by day (thumbnail, name, map, kills as dots, time, length).
  The selected clip shows in a right panel with a preview, its details and **Add to
  reel (A)**, **Favourite (F)** and **Open in editor (E)**. Arrow keys move between rows.
- **Grid:** 16:9 frames four across, with the length on the frame and the kills and
  map underneath.
- The Looks tab drops the "126,091,603,146,600 reels" headline. It becomes the same
  calm list or grid of looks, grouped by drawer.

### Studio, your reels — **picked: B, list with a phone preview**

Either fixes today's letterboxing (a 9:16 reel in a 16:9 tile) and moves Delete into a
"..." menu.

- **A. Poster wall:** reels tall, six across, length on the poster, song and date under.
- **B. List with a phone preview:** rows of name, song, length and date; the selected
  reel plays in a 9:16 preview with Open timeline (Enter), Show in folder (O) and
  Make a copy (D).

### Studio, making a reel — **picked: B, steps across the top**

The same five steps **in today's order: Style, Clips, Song, Look, Check** (the samples
show them in a different order by mistake). No new engine or storage work:

- **The preview** is the existing Look-step 9:16 preview (v1.90.0) on the chosen clip.
  On the other steps it is the chosen clip's still, framed as the reel will be.
  Nothing is rendered before Check.
- **"Saved as you go" is dropped** unless the guided maker already keeps its draft.
  The builder checks `studio.gd` and keeps whatever exists today.

- **A. Steps down the side:** a step list on the left showing each choice, the step
  in the middle, a live 9:16 preview on the right.
- **B. Steps across the top:** numbered steps as tabs, full width for the step, and a
  bottom bar with the reel so far and Next (Enter).

### Clips — **picked: A, then B (a mix)**

Recordings newest first, grouped by day, each with a status mark (not clipped / working
with % and time left / done with clip and kill counts). A video from elsewhere is
dropped on the list or chosen from a link.

- **A. List and summary:** a selected recording shows a filmstrip with the part to clip,
  then four numbered steps already filled in (part, how kills are found, clip settings,
  optional review), each with Change, which opens today's step screen, and **Cut clips
  (Enter)** / Review first.
- **B. Timeline of moments:** a selected recording opens as a timeline (matches as
  labelled bars, each kill a tick, taller for multi-kills; drag to limit the part)
  above the list of found moments to untick, with **Cut N clips (Enter)**.

**The mix the player asked for:** a recording opens on A (the list and the four-step
summary). Pressing the main button runs the scan, as today, and the moments it finds
open as B's timeline, with the list to untick before **Cut N clips**. B takes the place
of today's "Review the clips before cutting" screen, so review stops being an optional
detour and becomes the screen between scanning and cutting. A recording that is already
clipped opens straight on B, showing what was cut.

`clip_found()` still decides whether results are called kills or loud moments.

### Library — **picked: A, games and other apps with switches**

Fixes the list of 79 "games" that includes system tools.

- **A. Games and Other apps tabs:** game rows with a cover, source, clip count, and
  Records / Goes live switches. Other apps hold the rest and can be moved across.
- **B. Cover grid:** games as pictures with one line saying what happens when they open;
  other apps hidden unless added.

### Settings — **picked: A, grouped sections**

Plain labels with one line of help. Config keys (`ui.theme`) leave the main view and
show only under Advanced. Sections are grouped by task: App (General, Appearance,
Shortcuts), Streaming (Going live, OBS, Titles and thumbnails, Safety), Making clips
(Recording, Clips, Games), Advanced.

- **A. Grouped sections:** section list on the left, label/help/control rows on the
  right, search in the top bar.
- **B. Search first:** one large search that finds settings by what they do, with
  results grouped by section.

### Logs (decided)

Everything / Problems switch, search, Build a report. Problems are explained in a
sentence at the top, with the fix as a button where one exists. The log stays monospace.

### First-run setup (`ui/setup.py`)

Restyled to the same system. Its flow is unchanged. It is the first screen a stranger
meets, and it gains ARIA (roadmap UI item: `setup.py` has none).

## New behaviour (beyond restyling, agreed or proposed)

| Change | Status |
|---|---|
| App opens on the Dashboard | agreed |
| Chat on the right half, with the !clip row, first-message marker and new-messages pill | agreed |
| Dashboard first-run checklist, and the "Since last time" panel | agreed |
| Global Ctrl K that also searches clips, reels, games and settings | agreed |
| Five themes become System / Dark / Light, with migration | agreed (dark and light) |
| Library splits games from other apps, with Records / Goes live switches | agreed |
| Settings hide config keys outside Advanced | agreed |
| Logs explain problems in a sentence with a fix button | agreed |

**Settings > Shortcuts** is a home for the hotkeys that already exist
(`rules.replay_hotkey`, `rules.kill_switch_hotkey`, and the command registry's keys in
`ui/commands.py`) and the key sheet. Rebinding is not added (Designer's call).

**"New" (Designer's call):** a clip is new
until the Clips or Studio page has shown it once. The newest-seen time is kept in
`state.json`, so "3 new" survives a restart.

## Decided with the player after the builder check

1. **All four phases go out together as one PR** (his words: "do four phases at once
   then open a single PR"). They are built in order: the tokens, fonts and shell first,
   then the Dashboard and Logs, then the Studio clips and reels, then the reel maker
   and Clips, then Library, Settings and setup. One branch, one version bump, one release.
2. **Screens without a sample are restyled only.** That covers the Studio editor tabs
   (Timeline, Song, Facecam), the full Make page, the Clips page's reel maker
   (`ui/reel.py`) and the Clips step screens behind Change. They get the new tokens,
   type and controls, and keep their layout. Timeline, Song and Facecam stay reachable
   from the Studio top bar.
3. **Every proposed new behaviour stays:** the first-run checklist, "Since last time",
   Ctrl K that also searches clips, reels, games and settings, config keys hidden
   outside Advanced, and Logs explaining problems with a fix button.

## Left to the builder

- Exact token values for hover, focus and disabled states, measured for contrast.
- How the existing CSS sections in `css.py` are reorganised, provided the contract holds.
- The order pages are migrated in. The Dashboard and shell go first because the app
  opens there.
- Icon drawings, as long as they stay one consistent line set.
- Whether the old theme ids are kept in `theme.py` as aliases or migrated in `cfg.py`.

## Samples

`Desktop\AutoStream-UI-samples\index.html` has every screen above with the player's own
clips. The build script that made it is kept outside the repo. Earlier rejected
directions (three Valorant-inspired looks) are recorded here so they aren't proposed
again.
