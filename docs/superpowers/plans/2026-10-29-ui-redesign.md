# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every AutoStream page one calm, premium look in dark and light, on the
layouts the player picked, with all four phases shipped as one PR.

**Architecture:** The colours are in `autostream/theme.py`. The rest of the look is the
structural tokens and primitives in `autostream/ui/css.py`. Each page is one module
in `autostream/ui/`, assembled into one document by `autostream/ui/__init__.py` and
served by `webui.page()`. The foundation tasks (1–4) change tokens, primitives and the
shell, so every page restyles at once. The page tasks (5–14) change markup and JS only
where the player picked a new layout. Everything else is restyled through the tokens
alone (Task 15).

**Tech Stack:** Python 3.12, plain HTML/CSS/JS strings, pytest (offline), Playwright
browser tiers in `tests/verify` (`-m ui`, `AUTOSTREAM_VERIFY_SOURCE=1`).

**Spec:** `docs/superpowers/specs/2026-10-29-ui-redesign-design.md`

## Global Constraints

- No literal colour outside `autostream/theme.py`. The only exceptions are
  `--on-media*` in css.py and the `rgba()` already in theme tokens.
- Tokens name roles. Token names in `theme.TOKENS` are kept, and values change.
- The accent is the primary text colour. It is used in four places: sidebar selection
  bar, settings-nav selection bar, primary button, focus ring.
- Colour is never the only channel: every status pairs a shape or word with its colour.
- Spacing on the 4px grid (`--space-*`); focus ring on `:focus-visible` only.
- One top-level JS scope; new names are prefixed (`shell_`, `dash_`, `lib_`, `set_`,
  `log_`, `st_`, `clip_`, `pal_`).
- Text ≥ 4.5:1 on bg, chrome, surface, surface-raised and surface-sunken. Control
  borders (`border-strong`) ≥ 3:1 on the same grounds. Both themes are measured with
  the WCAG 2.x formula.
- Dark values: bg `#141519`, surface `#191A1F`, raised `#202228`, active `#2A2C33`,
  text `#ECEDEF`/`#A0A3AB`/`#868A93`, live/danger `#F2626A`, ok `#5CC8A8`,
  warn `#E5B454`, border-subtle white 7%, border-strong white 38%.
- Light values: bg `#F4F4F6`, surface `#FFFFFF`, raised `#F0F1F3`, active `#E3E4E8`,
  text `#18191C`/`#55585F`/`#666A72`, live/danger `#BF2C34`, ok `#167A5C`,
  warn `#94610F`, border-subtle black 8%, border-strong black 45%.
- Radii: 6px controls, 8px panels, 10px window and overlays. Base text 13px, secondary
  12px, section title 15px, page title 20px; tabular figures for numbers.
- Copy: sentence case, no all-caps labels, no eyebrow labels, no `->` on buttons, no
  `A · B · C` meta strings. Monospace only for log lines.
- Font: `"Instrument Sans", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif`.
  Instrument Sans is used if bundled. Downloading it needs the player's permission,
  so the stack must look right without it.
- Theme ids are `system`, `dark` and `light`. `midnight`, `carbon`, `ember` and
  `forest` read as `dark`, and `daylight` reads as `light`.
- The app opens on the Dashboard.
- Every DOM id or `data-act` that `tests/verify` drives is kept, or the test moves in
  the same task. `REACHED_FLOOR` (132) must not drop.
- Nothing a test runs opens a window (`AUTOSTREAM_NO_DIALOGS=1`, `appd.NO_WINDOW`).
- macOS: `autostream/macos/` is not edited. Shared modules must render without an
  engine (no state line) and without a tray (Quit stays in the sidebar).

## Review Focus

1. **A saved legacy theme id** (`carbon` in an old config.yaml) must load as dark, not
   fall back silently or error. Test in Task 1.
2. **System theme with Windows in light mode** must paint light everywhere, including
   after a live theme switch with no reload. Test in Task 1 (CSS emitted) and Task 16
   (browser).
3. **Chat with 120 messages and the reader scrolled up**: new messages must not yank
   the scroll; the pill must count them. Test in Task 6.
4. **A fresh install with no OBS, no games and no microphone**: the checklist must show
   every item unticked with its fix button, and no blank cards. Test in Task 7.
5. **Long names** (a 60-character reel title or game name) must truncate with an
   ellipsis in rows and the inspector, not wrap the row. Test in Tasks 9 and 10
   (browser).

---

### Task 1: Themes become System, Dark and Light

**Files:**
- Modify: `autostream/theme.py` (THEMES, DEFAULT, `get`, `css_vars`, `listing`;
  add `ALIASES`, `resolve`, `root_css`)
- Modify: `autostream/webui.py:237-246` (`page()`), `:889-896` (`/api/theme`), `:675`
- Modify: `autostream/cfg.py:213` (default `ui.theme` → `"system"`)
- Modify: `autostream/schema.py:60-75` (theme options)
- Modify: `autostream/ui/settings.py:344-360, 1083-1130` (picker, repaint)
- Test: `tests/test_theme.py` (create)

**Interfaces:**
- Produces: `theme.THEMES: {"dark": {...}, "light": {...}}`;
  `theme.ALIASES: dict[str, str]`; `theme.resolve(name: str | None) -> str` (returns
  `"system" | "dark" | "light"`); `theme.root_css(name: str | None) -> str` (a complete
  CSS text: `:root{...}` and, for system, `@media (prefers-color-scheme: light){:root{...}}`);
  `theme.listing() -> [{"id","label"}]` in the order System, Dark, Light.
  `webui.page()` puts `root_css` in `<style id="theme-vars">` before the main sheet.

- [ ] **Step 1: Write the failing tests** in `tests/test_theme.py`:
  - `test_text_reads_at_4_5_on_every_ground[dark|light]`: for text-primary, secondary
    and tertiary against bg, chrome, surface, surface-raised and surface-sunken,
    contrast ≥ 4.5.
  - `test_control_edges_read_at_3[dark|light]`: `border-strong` composited over
    surface, raised and sunken gives ≥ 3.0.
  - `test_state_colours_read_as_text[dark|light]`: live, ok, warn and danger are each
    ≥ 4.5 on surface.
  - `test_legacy_ids_resolve`: `resolve("carbon") == "dark"`,
    `resolve("daylight") == "light"`, `resolve("nonsense") == "system"`,
    `resolve(None) == "system"`.
  - `test_system_carries_both_palettes`: `"prefers-color-scheme: light"` is in
    `root_css("system")`, and not in `root_css("dark")`.
  - `test_listing_is_system_dark_light`: the ids are `["system", "dark", "light"]`.
- [ ] **Step 2: Run `.venv\Scripts\python.exe -m pytest tests/test_theme.py -q`**. Expect
  them to fail.
- [ ] **Step 3: Implement.** Use the Global Constraints values. Blend `rgba()` borders
  over the surface in the test helper. Keep every token in `TOKENS`; the legacy aliases
  mirror their semantic twins. `accent` is text-primary, `text-on-accent` is surface,
  `border-focus` is text-primary. `/api/theme` accepts any id `resolve()` maps to
  itself (system, dark, light). `set_repaint()` re-reads `<style id="theme-vars">` from
  a fetched page and replaces that element's text, clearing any inline `--` properties.
  The Appearance picker becomes a segmented control with System, Dark and Light.
- [ ] **Step 4: Run** `tests/test_theme.py tests/test_css_contrast.py tests/test_ui_wiring.py`, and fix any test that names an old theme id.
- [ ] **Step 5: Commit** `theme: System, Dark and Light replace the five themes`.

### Task 2: Structural tokens and primitives

**Files:**
- Modify: `autostream/ui/css.py` sections 1–8 (tokens, reset, type utilities,
  surfaces, buttons, forms, data display)
- Test: `tests/test_css_language.py` (create)

**Interfaces:**
- Produces: CSS classes keep their names (`.btn`, `.btn-primary`, `.btn-ghost`, `.card`,
  `.panel`, `.pill`, `.seg`, `.field`, `.toggle`...). New: `.kb` (key hint), `.mark`
  (status mark), with modifiers `.mark-idle` (empty ring), `.mark-work`
  (pie, `--p` 0–100), `.mark-done` (tick), `.mark-need` (dashed ring) and
  `.mark-live` (filled dot).

- [ ] **Step 1: Write the failing tests** in `tests/test_css_language.py`:
  - `test_no_uppercase_text_transform`: zero `text-transform:uppercase` in the sheet.
  - `test_monospace_only_where_allowed`: every rule that uses `var(--font-mono)` has a
    selector in an allowlist (log lines, `code`/`kbd`/`pre`, and time codes in the
    editor timeline). The allowlist is a tuple in the test, with a comment per entry.
  - `test_radii_are_the_three_sizes`: `--radius-sm:6px`, `--radius-md:8px`,
    `--radius-lg:10px`.
  - `test_font_stack_leads_with_instrument_sans`.
- [ ] **Step 2: Run them** and expect them to fail.
- [ ] **Step 3: Implement.** Set the type scale (13/12/15/20). `--font-display`,
  `--font-text` and `--font-micro` are the one stack. Remove `letter-spacing` tracking
  on labels and every `text-transform:uppercase`. Primary button = `--accent` fill with
  `--text-on-accent`. Secondary button = raised fill with a `border-strong` edge. Ghost
  button = no fill. `.pill` becomes the `.mark` plus a sentence-case word. Shadows
  stay only on overlays.
- [ ] **Step 4: Run** the full offline suite, `.venv\Scripts\python.exe -m pytest -q`.
- [ ] **Step 5: Commit** `css: the calm primitives`.

### Task 3: Sentence-case status words everywhere

**Files:**
- Modify: `autostream/ui/shell.py`, `dashboard.py`, `library.py`, `logs.py`,
  `settings.py`, `setup.py`, `clips.py`, `studio.py`, `reel.py`: JS string literals
  that render statuses or labels in caps (`'IDLE'`, `'OFFLINE'`, `'WAITING'`, `'OFF'`,
  ...)
- Test: `tests/test_css_language.py::test_no_shouted_status_words`

- [ ] **Step 1: Write the test.** Scan `autostream.ui.JS` and `BODY` for
  `>[A-Z]{3,}<` and quoted `'[A-Z]{3,}'` that reach text. Keep an allowlist for
  acronyms (OBS, API, GPU, FPS, HUD, ACE, MVP, URL, OAuth, CS2, YouTube) and for phase
  keys compared in code, not rendered.
- [ ] **Step 2: Run it** and expect it to fail.
- [ ] **Step 3: Implement.** Map phase keys to words through one shell helper,
  `shell_phaseWord(phase) -> 'Idle' | 'Live' | 'Starting' | ...`, and render through it.
- [ ] **Step 4: Run** the offline suite.
- [ ] **Step 5: Commit** `ui: say statuses in words, not caps`.

### Task 4: The shell: sidebar, state line, slim top bar, home

**Files:**
- Modify: `autostream/ui/shell.py` (`_RAIL`, `_TOPBAR`, `SHELL_JS` boot and poll)
- Modify: `autostream/ui/css.py` section 4 (shell) and 15 (responsive)
- Test: `tests/test_ui_wiring.py` (ids), `tests/verify/test_ui_playwright.py` (if it
  names `#top-pill` or `#top-clock`)

**Interfaces:**
- Produces: the sidebar holds `#rail-search` (opens the palette, shows `Ctrl K`), the
  nav, an optional page section host `#rail-section`, and `#rail-state` (mark plus
  "Live, 1:24:07" / "Recording, 0:12:40" / "Idle, not recording"). `#rail-quit` stays
  last. The top bar is 44px: `#topbar-title` (a breadcrumb), and `#topbar-actions`, a
  host pages fill through `shell_setActions(html)`. `#top-pill`, `#top-clock` and
  `#top-game` stay in the DOM, hidden, while any test reads them.
  `shell_railSection(html|null)` lets a page put its own list in the sidebar (Studio
  games).

- [ ] **Step 1: Test.** Extend `test_every_id_the_script_reaches_for_exists` (already
  generic). Add `test_the_app_opens_on_the_dashboard`: `SHELL_BOOT.home` defaults to
  `'dash'`.
- [ ] **Step 2: Implement** the markup and the state line painted from the status poll.
  Quit sits under the state line. Below 900px the sidebar collapses to icons with
  labels on hover and focus.
- [ ] **Step 3: Run** the offline suite. Then check in a browser with
  `AUTOSTREAM_VERIFY_SOURCE=1` and the screenshot script (Task 16) for both themes.
- [ ] **Step 4: Commit** `shell: sidebar with the app's state, slim top bar`.

### Task 5: Ctrl K on every page, searching everything

**Files:**
- Modify: `autostream/ui/commands.py` (`studio.palette` → global `app.palette`, scope
  `"app"`)
- Modify: `autostream/ui/studio.py` (palette code moves out; Studio registers commands)
- Modify: `autostream/ui/shell.py` (palette overlay and key handler)
- Test: `tests/test_studio_commands.py` (the scope change), `tests/test_palette.py`
  (create)

**Interfaces:**
- Produces: `pal_open()`, `pal_close()`, and
  `pal_source(name: string, fn: (q) => [{group, label, hint, keys, run}])`. Pages
  register providers: Studio ("Clips", "Reels"), Library ("Games"), Settings
  ("Settings"), commands ("Actions"). Results are grouped in the order Clips, Reels,
  Games, Actions, Settings, at most 6 per group. Up and Down move, Enter runs, Esc
  closes.

- [ ] **Step 1: Test** (`tests/test_palette.py`): the Ctrl+K binding's scope is
  `"app"`, and each of `lib_`, `set_` and `st_` calls `pal_source(` once (text scan of
  the JS).
- [ ] **Step 2: Implement.** Providers search data their page already holds, or fetch
  it once on first open (`/api/studio/library`, `/api/settings/schema`, the apps from
  `/api/status`).
- [ ] **Step 3: Run** the offline suite.
- [ ] **Step 4: Commit** `ui: Ctrl K finds clips, reels, games and settings from anywhere`.

### Task 6: Dashboard, live

**Files:**
- Modify: `autostream/ui/dashboard.py` (HTML and the DASH_JS paint)
- Modify: `autostream/ui/css.py` section 9
- Modify: `autostream/webui.py` `status()`: add `"marks": [{"at": float, "by": str}]`
  from `engine._marks`
- Test: `tests/test_dashboard_chat.py` (create; the JS helpers ported as pure
  functions and tested through the bundle text where they are pure), plus the verify
  tier

**Interfaces:**
- Produces: `dash_chatRows(msgs, marks, seenAuthors) -> [{kind: 'msg'|'mark', ...}]`
  merges chat and marks in time order. A message whose text is exactly `!clip` is
  folded into its mark row. `first` is true for an author's first message since the
  page loaded the live session.

- [ ] **Step 1: Tests.** `status()` returns `marks` (fake engine in `tests/fakes.py`).
  The bundle contains `#dash-chat-new` (the pill) and `#dash-chat-hint`.
- [ ] **Step 2: Implement the layout:**
  - The status line (game thumbnail, "Live on YouTube", game and map, clock, Pause P,
    Stop recording, End stream).
  - Below it, two halves. The left half holds the 2x2 numbers, the graph, replay (F9)
    beside health, and audio. Health shows skipped and total frames and congestion
    only. The right half is chat at full height.
  - Chat:
    - 14px text with the time on each message, and a Mod badge.
    - Mark rows. While the phase is LIVE they read "Watch after the stream"; after
      the stream, Watch calls `go('clips')` and selects that session at the mark.
    - The first-message marker, using the ok-colour bar and the word "First message".
    - The pill. It counts arrivals while `scrollTop` is not at the bottom, and
      clicking it scrolls down.
    - `/` focuses the input, unless focus is already in a field.
    - The hint: "Enter sends. Each message uses 50 of today's 10,000 YouTube units."
      It shows only when `has_quota` is true.
- [ ] **Step 3: Run** the offline suite and `tests/verify -m ui -k dash` with
  `AUTOSTREAM_VERIFY_SOURCE=1`.
- [ ] **Step 4: Commit** `dashboard: live chat on the right half`.

### Task 7: Dashboard, idle (first run and ready) and "Since last time"

**Files:**
- Modify: `autostream/ui/dashboard.py`, `css.py` section 9
- Modify: `autostream/webui.py`. Add GET `/api/since`, which returns
  `{"clips_new": int, "since": float|null, "last_session": {...}|null,
  "reels": [{"name","path","made"}]}` (up to 3 reels newer than `since`). Add POST
  `/api/seen` with `{"what": "clips"}`, which stamps `state.json` `ui_seen_clips` with
  the current time.
- Modify: `autostream/state.py` (the `ui_seen_clips` field)
- Test: `tests/test_since.py` (create)

- [ ] **Step 1: Tests.** `/api/since` counts clips newer than the stamp. `/api/seen`
  moves it, and the stamp survives a reload of `state.json`. The route is listed for
  `test_every_route_the_page_calls_exists`.
- [ ] **Step 2: Implement the checklist.** It shows OBS found (`obs.connected`, or an
  OBS path found), games found (any app with `game`), a microphone chosen (from the
  audio route), and going live (platform ready, or off). Each unticked item has the
  button that fixes it: Settings OBS, Library, the mic picker, platform sign-in. When
  everything is ticked, "Ready, waiting for a game" shows the trigger games, Start
  recording now, Go live now (only if going live is on), "Since last time", and the chat
  half's explanation. Clips and Studio POST `/api/seen` when they show clips.
- [ ] **Step 3: Run** the offline suite and the dash verify tests.
- [ ] **Step 4: Commit** `dashboard: a checklist for the first run, and what's new since last time`.

### Task 8: Logs, with problems explained

**Files:**
- Modify: `autostream/ui/logs.py`, `css.py` section 11
- Create: `autostream/logexplain.py` with `PROBLEMS: list[dict]`, each
  `{"match": regex, "say": str, "fix": {"label": str, "act": str} | None}`, and
  `explain(line: str) -> dict | None`
- Modify: `autostream/webui.py` (`/api/logs/tail` adds `"problems"`: explained lines,
  newest first, deduplicated by `say`)
- Test: `tests/test_logexplain.py` (create)

- [ ] **Step 1: Tests.** One case per rule:
  - `quotaExceeded` → "today's YouTube API budget ran out", no fix.
  - OBS not reachable → "OBS isn't running or its websocket is off", fix "Open OBS
    settings".
  - ffmpeg missing → "ffmpeg isn't installed", fix "Install tools".
  - Dropped frames over 1% → "OBS is dropping frames", no fix.
  - Disk low → "the recording drive is nearly full", fix "Change folder".
  - An unknown error line → `None`.
- [ ] **Step 2: Implement.** The Everything / Problems segmented control, search, and
  Build a report (existing). Problem rows sit above the log. Log lines stay monospace.
- [ ] **Step 3: Run** the offline suite.
- [ ] **Step 4: Commit** `logs: say what went wrong and offer the fix`.

### Task 9: Studio clips: list with a side panel (default) and grid

**Files:**
- Modify: `autostream/ui/studio.py` (the browser: folders, runs, clips), `css.py`
  (studio browser block)
- Test: verify tier `tests/verify/test_ui_playwright.py` (Studio browse cases);
  `docs/UI-SCENARIOS.md`

**Interfaces:**
- Consumes: `shell_railSection` (Task 4) for the games list with counts and Favourites;
  `shell_setActions` for the Clips / Reels / Looks switch, Filter, and Make a reel (R).
- Produces: `st_view` (`'list'` | `'grid'`), persisted in localStorage under
  `as.studio.view`. In list view: rows grouped by day, the `#st-insp` inspector, and the
  A, F and E keys while a row is focused.

- [ ] **Step 1: Write the UI scenarios** in `docs/UI-SCENARIOS.md` (list default,
  arrows move, A adds, F favourites, E opens, grid remembered, long name truncates).
- [ ] **Step 2: Implement.** Drop the "Pick your clips, then pick a look" hero and the
  "Reel maker" eyebrow. Folders become the sidebar's game list, and a game opens on its
  clips. Runs and matches become day and match group headers.
- [ ] **Step 3: Run** the offline suite and `tests/verify -m ui -k studio`, with
  `AUTOSTREAM_VERIFY_SOURCE=1`.
- [ ] **Step 4: Commit** `studio: clips as a list with a side panel`.

### Task 10: Studio reels: list with a phone preview

**Files:** `autostream/ui/studio.py` (reels tab), `css.py`

- [ ] **Step 1: Scenarios:** selecting a row plays it in the 9:16 preview; Enter opens
  the timeline; O shows it in its folder; D makes a copy; Delete sits in the row's
  "..." menu and still confirms.
- [ ] **Step 2: Implement.** Rows show name, song, length and date. The inspector holds
  a `<video>` with `preload="metadata"` (not `none`; see CLAUDE.md on NaN durations).
- [ ] **Step 3: Run** the Studio verify tests.
- [ ] **Step 4: Commit** `studio: reels as a list with a phone preview`.

### Task 11: Reel maker: steps across the top, summary at the bottom

**Files:** `autostream/ui/studio.py` (guided maker, `studio.gd`), `css.py`

- [ ] **Step 1: Scenarios:**
  - The steps are in today's order (Style, Clips, Song, Look, Check).
  - A done step is clickable.
  - The bottom bar shows the reel so far and Next with Enter.
  - The Look step keeps its live 9:16 preview.
- [ ] **Step 2: Implement.** Restyle the existing stepper as tabs, and move the next
  and back buttons to a sticky bottom bar. No new draft storage.
- [ ] **Step 3: Run** `tests/verify -m ui -k "guide or maker or reel_flow"`.
- [ ] **Step 4: Commit** `studio: the reel maker's steps across the top`.

### Task 12: Clips: list and summary, then the timeline of moments

**Files:** `autostream/ui/clips.py`, `css.py` (clips block), `docs/UI-SCENARIOS.md`

**Interfaces:**
- Consumes: today's sessions list, `clip_found()`, and the review data used by
  "Review the clips before cutting" (the kills found by the scan).
- Produces:
  - **Screen A** (`#clip-sum`): the list of recordings with status marks, and the
    four-step summary, each with Change opening today's step screen. The main button
    reads "Find kills" (or "Find loud moments" via `clip_found`).
  - **Screen B** (`#clip-moments`): it replaces the review screen as the step after the
    scan. It shows a timeline with match bars from the known matches, ticks sized by
    kill count, and a drag to limit the part. Below are moment rows to untick, and
    "Cut N clips". A recording that already has clips opens on B, showing what was cut.

- [ ] **Step 1: Scenarios:**
  - An unclipped recording opens on A.
  - Pressing the main button scans, then shows B.
  - Unticking a moment lowers N.
  - Cut runs the existing cut with only the ticked moments.
  - An already clipped recording opens on B.
  - A game with no profile says "loud moments".
- [ ] **Step 2: Implement.** Reuse today's review data and cut call, and keep every
  `data-act` the verify tests use.
- [ ] **Step 3: Run** `tests/verify -m ui -k "clip"` with `AUTOSTREAM_VERIFY_SOURCE=1`.
- [ ] **Step 4: Commit** `clips: a summary to start, a timeline of moments to cut from`.

### Task 13: Library: games and other apps, with switches

**Files:** `autostream/ui/library.py`, `css.py` section 10, `autostream/webui.py`
(saving the two switches)

**Interfaces:**
- Consumes: `apps_payload()` (`game`, `stream`, `thumbnail`, `source`, `game_key`).
- Produces:
  - The Games tab (`game` true) and the Other apps tab.
  - **Goes live** saves `stream` through the existing apps save route.
  - **Records** (and "Move to Games" on an Other apps row) saves whether the exe is
    treated as a game, through the same `games.yaml` path `is_game` reads. If no
    override route exists, add POST `/api/library/game {"key", "game": bool}`, tested
    in `tests/test_library_game.py`.

- [ ] **Step 1: Test the route** if it is added.
- [ ] **Step 2: Implement** the rows: cover, name, source, clip count when known,
  Records, Goes live. Open and Open + stream stay in the row's "..." menu.
- [ ] **Step 3: Run** the offline suite and `tests/verify -m ui -k library`.
- [ ] **Step 4: Commit** `library: games apart from other apps, each with plain switches`.

### Task 14: Settings: grouped sections, plain labels; first-run setup restyled

**Files:** `autostream/ui/settings.py`, `autostream/schema.py` (section → group map),
`autostream/ui/setup.py`, `css.py` sections 12 and 14

- [ ] **Step 1: Tests:**
  - `test_every_section_belongs_to_a_group` (schema sections map to App, Streaming,
    Making clips or Advanced).
  - `test_keys_are_hidden_outside_advanced`: the setting key element renders only when
    the section is Advanced or `ui.developer_mode` is on (text scan for the guard).
- [ ] **Step 2: Implement:**
  - Group headings in the section nav.
  - Label, one line of help, and the control on the right.
  - Shortcuts lists the replay and kill-switch hotkeys and the command keys.
  - Setup gets ARIA labels and roles on every control and step.
- [ ] **Step 3: Run** `tests/verify -m ui -k "settings or setup"`.
- [ ] **Step 4: Commit** `settings: grouped by what you're doing, plain words`.

### Task 15: Restyle-only pass for the screens without a sample

**Files:** `autostream/ui/css.py` (studio, clips and reel blocks after line 2326),
`studio.py` (Looks header), `reel.py`

- [ ] **Step 1: Implement.**
  - Remove the Looks "Mix and match" big-number header, and keep the drawer list.
  - Remove the eyebrows and all-caps headings ("THE DRAWERS", "OPENING").
  - Replace the hard-coded radii and shadows with tokens.
  - The editor tabs (Timeline, Song, Facecam), the Make page and the Clips step screens
    keep their layout.
- [ ] **Step 2: Run** the offline suite, then the full UI sweep
  (`tests/verify -m ui -q -p no:randomly`).
- [ ] **Step 3: Commit** `ui: the remaining screens in the new look`.

### Task 16: Verify, document, version, PR

**Files:** `docs/UI-SCENARIOS.md`, `docs/ROADMAP.md` (Progress row), `docs/ARCHITECTURE.md`,
`README.md` (screenshot references), `docs/TESTING-UI.md`, `autostream/__init__.py`
(`__version__ = "2.0.0"`), `tests/verify/test_ui_sweep.py` (`REACHED_FLOOR` raised if
reach grew)

- [ ] **Step 1:** Screenshot every page in both themes and at 390px. Use a Playwright
  script against `AUTOSTREAM_VERIFY_SOURCE=1`, kept out of the repo, and look at each.
- [ ] **Step 2:** Run the offline suite, then the full UI sweep, in that order.
- [ ] **Step 3:** Update the docs and the Progress row, and bump the version.
- [ ] **Step 4:** Open one PR from `ui-redesign`, with a section per phase: what
  changed, why, and the evidence (test counts, screenshots).
