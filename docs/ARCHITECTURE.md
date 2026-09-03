# AutoStream — Architecture & Developer Reference

This document covers how AutoStream works internally: module responsibilities, the
state machine, configuration, and safety mechanisms. For installation and day-to-day
usage, see [`README.md`](../README.md).

AutoStream (`__version__ = "1.0.0"`, [`autostream/__init__.py`](../autostream/__init__.py))
is a Windows daemon that watches which process has foreground focus, resolves it to a
game via a merged exe→name index, and drives OBS + the YouTube Data API to start,
retitle, and stop a live broadcast automatically.

---

## 1. Entry point

`python -m autostream <command>` → [`autostream/__main__.py`](../autostream/__main__.py).
Each subcommand is a `cmd_*` function that lazily imports only the modules it needs, so
e.g. `detect` never touches the YouTube/OBS code paths at all.

`cmd_run` is the daemon entry point. It wires together, each on its own thread except
the main one:

- **main thread** — `window.MainWindow` (pywebview), because pywebview requires the
  main thread on Windows
- **engine thread** — `engine.Engine.tick()` loop, the only thread that performs side
  effects (starting/stopping streams)
- **HTTP thread** — `webui.Server`, the dashboard/setup-wizard backend
- **tray thread** — `tray.Tray` (pystray)
- **panel thread** — `panel.ControlPanel` (tkinter overlay HUD), unless `--no-panel`
- **hotkey listener** — global kill switch via the `keyboard` package

The UI layer (panel, tray, web dashboard) never calls OBS/YouTube directly. It calls
`engine.submit(command)` — a thread-safe queue — and reads `engine.state` for display.

## 2. Module map

| Module | Responsibility |
|---|---|
| [`__main__.py`](../autostream/__main__.py) | CLI parsing, logging setup, `run` command orchestration |
| [`cfg.py`](../autostream/cfg.py) | Loads/merges `config.yaml` + `games.yaml` with defaults; dotted-attribute config access; env-var password override |
| [`state.py`](../autostream/state.py) | `State` dataclass — persisted phase snapshot; atomic JSON write; quota-day rollover |
| [`engine.py`](../autostream/engine.py) | The state machine — the only place a broadcast is started/retitled/stopped |
| [`watcher.py`](../autostream/watcher.py) | Process polling + foreground-window/Steam-registry signals → resolves the "active game", no network I/O |
| [`gameindex.py`](../autostream/gameindex.py) | exe→game-name resolution: `games.yaml` overrides + Discord detectable-apps list + Steam applist, cached to `index.cache.json` |
| [`obs.py`](../autostream/obs.py) | obs-websocket v5 client wrapper: connect/launch OBS, configure stream service, start/stop, **pause/resume recording**, scene switching, health |
| [`youtube.py`](../autostream/youtube.py) | YouTube Data API v3 wrapper: OAuth, quota accounting, reusable-stream + broadcast lifecycle, chat, orphan sweep |
| [`titles.py`](../autostream/titles.py) | Pure string templating for stream title/description |
| [`notify.py`](../autostream/notify.py) | Windows toast notifications (no-ops if `winotify` missing) |
| [`catalog.py`](../autostream/catalog.py) | Discovers launchable apps (Steam/Epic/Start-Menu) for the dashboard's "Open"/"Open & stream" buttons; stored in `apps.yaml` |
| [`tray.py`](../autostream/tray.py) | System tray icon with status menu |
| [`window.py`](../autostream/window.py) | Native app window via pywebview, falls back to default browser |
| [`webui.py`](../autostream/webui.py) | Current stdlib HTTP server: themed dashboard + first-run setup wizard (JSON API + HTML) |
| [`web.py`](../autostream/web.py) | **Legacy** — an older dashboard server, superseded by `webui.py`; not wired into `cmd_run` |
| [`setup_flow.py`](../autostream/setup_flow.py) | Backend actions for the browser-based setup wizard |
| [`setup_wizard.py`](../autostream/setup_wizard.py) | Original console/interactive setup flow (`autostream setup`) |
| [`theme.py`](../autostream/theme.py) | Named CSS colour-variable sets for the web UI |
| [`ui_assets.py`](../autostream/ui_assets.py) | Raw CSS/HTML/JS for the themed dashboard |
| [`paths.py`](../autostream/paths.py) | Single source of truth for on-disk locations; `AUTOSTREAM_HOME` override |
| [`streamelements.py`](../autostream/streamelements.py) | Lists a channel's overlays so a screen saver can be picked from a list instead of a pasted URL. The JWT lives in `secrets\` (never `config.yaml`) and carries its own channel id and overlay token, so one paste is enough. Classifies each overlay by name — start / be-right-back / end — and SUGGESTS rather than applies, because a channel can hold two installs of the same theme |
| [`screens.py`](../autostream/screens.py) | The three screen savers — starting, be-right-back, ending. Each setting takes **a video file or an overlay URL**, and AutoStream creates the OBS scene itself — an `ffmpeg_source` for one, a `browser_source` for the other. Idempotent: it builds what is missing and updates what is there, and never removes or re-creates a source you have since moved, resized or filtered |
| [`history.py`](../autostream/history.py) | Append-only JSONL journal of finished sessions — the only durable record of which game ran on which broadcast, and where its recording is |
| [`thumbnail.py`](../autostream/thumbnail.py) | Composes a thumbnail from a live OBS frame, your logo and the game. A game can be assigned a finished image instead, which is used exactly as given — `use_as_is` only checks it exists and fits under YouTube's 2 MB limit, shrinking rather than refusing |

### `clips/` — optional clip production

Imported lazily behind `clips.available()`; needs numpy and ffmpeg, neither of which is
bundled. A missing dependency renders a setup card on the Clips page and changes nothing
else about the app. Reading a kill feed additionally needs Tesseract and `pytesseract`;
without them that one detector mode is greyed out **with a button that installs it**,
and every other game still works.

| Module | Responsibility |
|---|---|
| [`tools.py`](../autostream/clips/tools.py) | ffmpeg/ffprobe discovery (PATH, then winget's versioned package dirs), subprocess helpers, encoder selection |
| [`deps.py`](../autostream/clips/deps.py) | The tools that are **not** pip packages — ffmpeg and Tesseract. Discovery (Tesseract's installer does not touch PATH, so its own directories are searched), what each absence costs, and a winget installer on a worker thread whose progress rides the status poll. Import-light on purpose: `clips.status()` calls it on every Clips page load and must answer before numpy is imported. Nothing installs without being asked — these are machine-wide installs that raise a UAC prompt |
| [`profiles.py`](../autostream/clips/profiles.py) | Per-game detector profiles: search band, **detector mode**, template file, **reference height**, match threshold, whether the game writes a readable demo (`demos`), and per-game floors under the timing style (`pre_roll_min` / `tail_min`). Also **declares what each mode needs** — `requirements()` / `missing()` — so a gap is caught before a scan starts rather than minutes into one, and anything that can be measured off the user's own footage is never asked for. Built-ins plus `config/clip_profiles.yaml` |
| [`detect.py`](../autostream/clips/detect.py) | Normalised cross-correlation scan for the marker. Chunked across a thread pool; rescales every band to the profile's reference height before matching. Dispatches `mode: killfeed` to `killfeed.py` |
| [`killfeed.py`](../autostream/clips/killfeed.py) | For games that draw no kill marker (Counter-Strike 2): OCRs the kill feed, finds the player's own name, and reads kill/death/assist off *where* it sits on the line. Needs Tesseract |
| [`valorant_feed.py`](../autostream/clips/valorant_feed.py) | Valorant, `mode: feedbar`. OCR reads the player's own name in only 13-16% of the frames it is on screen, so the feed's **coloured bars** are read instead: the game outlines your own half of a row in yellow, and which end it is on says kill or death. No OCR, no name, nothing to configure |
| [`cs2_cards.py`](../autostream/clips/cs2_cards.py) | Counter-Strike, `mode: cardcount`. Reads the round kill tally under the crosshair — `width = 18 + 16 x kills` — with a flash marking each kill and the settled width confirming the count. The HUD colour is a game setting, so it is measured from the recording, not assumed |
| [`cs2_demo.py`](../autostream/clips/cs2_demo.py) | Counter-Strike `.dem` parsing via `demoparser2`, plus the **fingerprint sync** that maps demo time onto the recording. Gives exact kills, deaths, rounds, **per-round rosters** (so the half-time swap needs no detecting) and the flags no detector can infer (`thrusmoke`, `attackerblind`). Refuses rather than guessing when the alignment is weak, and `audit()` marks the pixel detector against it |
| [`beatsync.py`](../autostream/clips/beatsync.py) | Tempo, beat phase and the drop from a spectral-flux onset envelope — deliberately written out rather than pulling in librosa, scipy and numba. Owns the `Slot` layout type and the cut/join/mux stage both arrangements share |
| [`story.py`](../autostream/clips/story.py) | The arrangement above the beat grid: clips stay **chronological** and the *music* is offset so the drop lands on the session's peak. Acts (opening / slide / turn / push / close), phrase-aligned act changes, a density ramp into the turn, and an intensity floor so a clutch is never flash-cut |
| [`voice.py`](../autostream/clips/voice.py) | Spoken hooks from **Kokoro-82M** (ONNX, CPU). The round's labels choose a pool of lines and the clip's position chooses one, so a re-cut says the same thing and two clutches do not; a clip with nothing to say stays silent. Ducks the game under the voice, and `catalogue()`/`samples()` are how a voice gets chosen by ear. Optional 177 MB download |
| [`plan.py`](../autostream/clips/plan.py) | Clusters kills into fights, picks the densest window of the requested length, ranks and names. Timing styles live here; per-game floors under them live on the profile (`pre_roll_min` / `tail_min`) |
| [`cutter.py`](../autostream/clips/cutter.py) | Cuts masters (all audio tracks kept), verticals and contact sheets |
| [`promo.py`](../autostream/clips/promo.py) | Sweeps the clips that fell BELOW `min_kills` into one vertical advert for the channel. A single kill has nothing a caption could honestly claim about the play; a dozen of them cut to a few seconds each can honestly carry a claim about the channel |
| [`montage.py`](../autostream/clips/montage.py) | xfade/acrossfade chain with cumulative offsets |
| [`jobs.py`](../autostream/clips/jobs.py) | `ClipJob` + `JobRunner`: one job at a time on its own thread, progress published through `/api/status` |
| [`calibrate.py`](../autostream/clips/calibrate.py) | Turns a dragged box into a template, then judges it by detection rate across the recording. For killfeed games the box *is* the band, and what gets proved instead is that the name is legible in it |

**Two detector modes, because not every game has a marker to match.** Most shooters
confirm your own kill with a fixed glyph — Delta Force draws a skull under the crosshair —
and a template match is both cheap and unambiguous. Counter-Strike 2 draws nothing at all
and announces kills only in the feed, which lists *everyone's*. So its profile sets
`mode: killfeed` and the feed is read instead:

- **Which slot the name occupies is the signal**, not its presence — the line reads
  `KILLER [+ assister] <icon> VICTIM` and your name can be in any of the three. Measured
  over 12 minutes of play, kill sightings ended at 0.594–0.828 of the strip and deaths at
  0.966–0.988, with nothing in between; the feed is right-aligned, so only a victim's name
  reaches the margin.
- **Colour was tried first and rejected.** CS2 does outline your rows red, but over sandy
  terrain a *kill* row measured redness 60 against a genuine *death* row's 26 — the map
  decides how red a row is, not the outline. The outline also marks rows you merely
  assisted, so even read perfectly it would not separate a kill from a death.
- **Assists are detected and excluded.** Counting them would put "3 kills" on a clip where
  the player got one.
- **Cost:** roughly a minute of scanning per ten minutes of footage, against seconds for a
  template match. `scan_fps` is 1.0 because a feed row lives a median of 5 seconds.

Every constant above is measured, and the measurements are pinned in
[`tests/test_killfeed.py`](../tests/test_killfeed.py) so moving one fails loudly.

**The two things that fail silently here**, both guarded and tested:

1. **Reference height.** A template is a fixed pixel patch. Matched against a frame at
   the wrong scale it returns *zero* hits, which is indistinguishable from a session with
   no kills. `Profile.ref_height` records the height the template was cut at and every
   scan rescales to it. The shipped Delta Force value of 720 was found by sweeping
   540–900 against 64 known kills; it peaked at 720 and collapsed to nothing either side.

2. **Crop arithmetic.** ffmpeg *rounds* a fractional crop where `int()` truncates
   (204.8 → 205 vs 204). Predicting the band size rather than computing it misaligns the
   raw-frame reshape by a pixel per row and the scan quietly returns nothing.
   `band_geometry()` computes integers up front and hands ffmpeg literal values.

**Counter-Strike rounds come from the demo where there is one.**
[`rounds.py`](../autostream/clips/rounds.py) was written against pixels: the score from
template-matched HUD digits, the alive counts beside them, and which side was the
player's from correlating their deaths against those counters. All of it works, and all
of it is inference. `rounds.from_demo()` builds the same `Round` objects out of Valve's
own record instead, and three things change:

- **1vN is counted, not inferred.** Every death in the demo names the side that lost a
  player, so the alive counts are a countdown from the roster rather than two OCR'd
  digits. The check the pixel path needs — "am I the last one alive, or am I dead and
  watching the last one alive" — cannot arise.
- **The half-time swap stops being a problem.** On the scoreboard the same match reads
  2-10 before the swap and 10-2 after, and `halves()` exists to spot the reversal.
  Rosters are read at every round's *freeze end*, so a swap is just the next round's
  answer. Verified on a real match: CT for rounds 1-12, T for 13-16, including round 13
  where the player got no kills and no deaths and the kill feed therefore said nothing.
- **Streaks, match point and the kill circumstances become arithmetic.** `round_end`
  gives the winner per round, `round_announce_match_point` gives match point, and the
  kill flags give `thrusmoke` / `penetrated` / `noscope` / weapon. Those are labelled
  because they are *rare* — measured over one full match, 4 smoke kills and 2 wallbangs
  in 115, against 48 headshots. A headshot is not a label for exactly that reason.

The detector still runs, because its kill times are the fingerprint that locates the
demo inside the recording — but nothing it reported survives into the clips once a demo
aligns, and `cs2_demo.audit()` then says what it got right. On the match this was built
against: **12 of 12 kills aligned, worst error 0.01s**, and one round labelled
`ALMOST 1v4` by the exact alive counts turned out to be a round where the player did
nothing and then died. That is now not a highlight — a lost last stand needs a kill in
it, which is a rule only exact counts could have shown was missing.

### Typical live-session data flow

```
watcher.py  (poll processes, foreground window, Steam registry — no network)
    │
    ▼
engine.py  IDLE → sees active game → _preflight() gating
    │
    ▼
engine.py  ARMING → same game survives arm_delay → _begin_session()
    │
    ├──► youtube.py  create_broadcast() + bind() to permanent stream
    ├──► obs.py      start(scene, overlay) → OBS pushes RTMP to YouTube
    └──► state.py    State.save() — always BEFORE the side effect above
    │
    ▼
engine.py  STARTING → poll youtube.stream_status() until ingestion active
    │
    ▼
engine.py  TESTING → hold abort_grace seconds (toast + kill-switch window)
    │
    ▼
engine.py  LIVE → watcher.active_game() for switches, obs.health(),
                   youtube.live_details()/chat, max_session_hours cap
    │
    ▼
engine.py  COOLDOWN → game gone → wait `cooldown` → STOPPING
    │
    ▼
engine.py  STOPPING → obs.stop(), youtube.transition(complete), reset → IDLE
```

### Screen savers, and what they did to pause

Three moments in a session are not about the game: arriving, stepping away, and
signing off. Each is an ordinary OBS scene holding one looping media source,
and `screens.py` **builds them** rather than asking the user to — obs-websocket
can create both a scene and an `ffmpeg_source`, so the setting is a file path
and the scene name is AutoStream's business.

| screen | on air | held by |
|---|---|---|
| starting | from go-live | `starting_seconds`, then the game scene |
| be right back | while paused | the pause itself — there is no timer |
| ending | before the broadcast completes | `ending_seconds` |

Both holds are **deadlines the tick loop checks**, never sleeps: that loop is
strictly serial, so sleeping in it would stop the OBS watchdog and chat for as
long as a card is up. The session also opens *on* the starting card rather than
switching to it, because starting on the game scene shows the game for a frame
or two at the top of every stream — the one moment the card exists to cover.

**This is why pause no longer ends the broadcast.** A card that says "be right
back" is a promise to come back, and it can only be kept if there is still a
broadcast to come back to; ending it and starting a fresh one loses the URL,
the chat and everyone watching. So `toggle_pause` on a LIVE session switches
the picture and nothing else. With no card configured there is nothing to
switch to, so it stops instead — a paused stream still showing the game is not
paused, it is unattended.

That left the kill-switch hotkey holding a stream up rather than ending one,
which is not a kill switch. It now sends `kill`, a separate command that pauses
*and* stops. The `rules.paused_flag_file` is unchanged: it is a "do not stream"
switch meant to be left in place, so it still ends the session.

### The same three controls when nothing is being broadcast

Pause, Resume and Stop are offered whether or not there is a broadcast, so they
have to mean something in both modes. With `youtube.enabled: false` the thing
under control is the **recording**, and each maps to the honest equivalent:

| control | streaming | recording only |
|---|---|---|
| Pause | be-right-back card, broadcast stays up | `obs.pause_recording()` — frames stop, the file stays open |
| Resume | back to the game scene | `obs.resume_recording()` — same file, no second output |
| Stop | ending card, then `complete` | `stop_record()`, journalled as usual |

Pausing a recording-only session onto the card would be the wrong analogue
twice over: nobody is watching it, and it would be written **into** the file
the clips are later cut from — minutes of a title card in the middle of the
footage. Resume continues the open file rather than starting a new one because
the cutter reads one file per session, so a second output would strand half of
it. If OBS refuses the pause the session stops instead, rather than reporting a
pause that did not happen while OBS keeps writing.

The LIVE watchdog never mistakes this for an outage: `_tick_live` returns as
soon as it sees `state.paused`, well before the output-health check that ends a
session after a 120-second outage.

The dashboard follows. The stop button cannot go on saying *End stream* when
nothing is being streamed, so it reads **Stop recording**; and the ingest panel,
which would otherwise sit on `OFFLINE` all session, reports the recording
instead — `RECORDING` / `PAUSED`, with its running length and size. That panel
is the only place a paused recording is visible, since the phase stays LIVE and
the file keeps its size.

### Clips-only mode (`youtube.enabled: false`)

AutoStream has two halves — it streams, and it clips — and the second is useful
on its own. With `youtube.enabled` off it still spots the game, still records
it, still journals the session and still cuts clips; it never touches the
YouTube API and needs no Google sign-in (`webui.is_configured()` returns True,
so the setup wizard is skipped entirely).

**The state machine is the same shape**, because what changes is only what a
session *does*. `Engine.streaming` gates the handful of places where it
differs:

| | streaming | clips only |
|---|---|---|
| `_begin_session` | broadcast + bind + `obs.start()` + record | `_begin_recording_only`: record, straight to LIVE |
| STARTING / TESTING | poll ingestion, hold `abort_grace` | skipped — there is no ingestion and nothing to hold |
| LIVE watchdog | `obs.is_streaming()` | `obs.recording_active()` |
| LIVE polling | viewers, likes, chat | none |
| game switch | retitle, or a new broadcast | nothing; the recording carries on |
| `_preflight` | quota headroom checked | quota is a YouTube concept, skipped |
| STOPPING | `obs.stop()` + transition to `complete` | stop recording, journal |

Two things are deliberately loud rather than silent. A clips-only session whose
recording fails to start is **abandoned** — the recording *is* the session, and
a LIVE phase with nothing being written looks healthy and produces nothing. And
if streaming and recording are both off, startup logs an error and toasts,
because that combination can only ever sit at IDLE.

The dashboard reads `streaming` out of `/api/status` and shows **RECORDING**
rather than LIVE, and hides the viewer/like counters and the chat column.

## 3. State machine

Phases are defined in [`state.py`](../autostream/state.py):

```
IDLE → ARMING → STARTING → TESTING → LIVE → COOLDOWN → STOPPING → IDLE
```

All transitions and their side effects live in `Engine`, driven by `Engine.tick()`,
which dispatches to one `_tick_<phase>` method per phase. `Engine._goto(phase)` is the
sole mutator: it always persists `state.save()` **before** running the phase's side
effect, so a crash mid-transition is always recoverable — `Engine._recover()` runs at
startup and sweeps any broadcast orphaned in `active`/`testing` via
`youtube.sweep_orphans()`.

| Phase | Trigger in | Behavior |
|---|---|---|
| **IDLE** | `_tick_idle` | Watches for an active game; runs `_preflight()`; on pass → ARMING |
| **ARMING** | `_tick_arming` | Waits for the same game to survive `timing.arm_delay` seconds (debounces brief/accidental launches) — skipped if the user clicked "Open & stream"; re-runs `_preflight()`; on pass → `_begin_session()` → STARTING |
| **STARTING** | `_tick_starting` | Broadcast + OBS stream already created; polls `youtube.stream_status()` until ingestion is active, bounded by `timing.ingestion_timeout` (else `_abandon_start()` back to IDLE) |
| **TESTING** | `_tick_testing` | Holds for `timing.abort_grace` seconds (broadcast is YouTube-side `testing`, i.e. private) — the kill-switch window — then `_go_live()` |
| **LIVE** | `_tick_live` | Enforces `max_session_hours`; checks pause/kill-switch and OBS health (120s outage grace); polls viewers/likes/chat; detects game switches via `_maybe_switch()` (further `timing.switch_delay` debounce), either retitling in place (`switch_policy: rolling`) or starting a fresh broadcast (`switch_policy: new_broadcast`, loops back to STARTING); no game → COOLDOWN |
| **COOLDOWN** | `_tick_cooldown` | Game back → straight to LIVE (as a switch if different); otherwise waits `timing.cooldown` seconds → STOPPING |
| **STOPPING** | `_tick_stopping` | `obs.stop()`, `youtube.transition(complete)`, resets session state and the watcher's arm debounce → IDLE |

Two controls force a phase change from outside the tick loop: `Engine.force_stop()`
(used by CLI `stop`, tray "End stream", dashboard, panel) and `Engine.toggle_pause()`
(the kill switch).

Three consecutive start failures auto-pause the engine (`_abandon_start`) until the
daemon restarts, to avoid a crash-loop hammering the YouTube API.

## 4. Configuration reference

Config lives in [`config/config.yaml`](../config/config.yaml) and
[`config/games.yaml`](../config/games.yaml), loaded by
[`cfg.py`](../autostream/cfg.py). A `DEFAULTS` dict is deep-merged under whatever is in
`config.yaml`, so any omitted key falls back to a sane default. `Config`/`Section`
give dotted attribute access (e.g. `cfg.obs.port`).

### `config/config.yaml`

| Section | Keys |
|---|---|
| `youtube:` | **`enabled`** (off = clips-only, see below), `privacy` (`unlisted` recommended initially), `latency`, `category_id`, `stream_id`/`ingestion_address` (written by setup — the permanent reusable stream), `made_for_kids`, `switch_policy` (`rolling` / `new_broadcast`) |
| `obs:` | `host`/`port` (4455), `password`, `password_env` (`AUTOSTREAM_OBS_PW`), path to `obs64.exe`, `default_scene`, `overlay_source`, `service_mode` |
| `timing:` | `poll_interval`, `arm_delay`, `abort_grace`, `switch_delay`, `cooldown`, `ingestion_timeout`, `max_session_hours`, `index_refresh_days` |
| `rules:` | `quiet_hours` (`[start, end]` as `HH:MM`), `require_ac_power`, `min_free_disk_gb`, `kill_switch_hotkey`, `paused_flag_file` (`NOSTREAM`), `quota_reserve`, `tray_icon`, `web_token` (dashboard auth token) |
| `title:` | `template` (placeholders like `{game} {hook} {day}`), `hooks` (rotating flavour text), `max_len`, `fallback_game` |
| `description:` | `template`, `tags` |
| `record:` | `enabled`, `directory`, `min_free_gb`, `warn_free_gb`, `auto_scan` |
| `clips:` | `output_dir`, `ffmpeg_path`, `min_kills`, `style`, `clip_seconds`, `pre_roll`, `tail_seconds`, `vertical_mode`, `transition`/`transition_ms`, `encoder`, `rounds`, `whole_round`, `voice`/`voice_name` (spoken hooks), `music`/`arc`/`order` (the beat-synced reel), `promo`/`promo_caption` (the leftovers reel) |
| `screens:` | `enabled`, `scene_prefix`, `starting_file`/`starting_seconds`, `paused_file`, `ending_file`/`ending_seconds`. Each `*_file` takes a path **or** an `http(s)` URL |
| `logging:` | `level`, `keep_days` |
| `ui:` | `theme` |

`Config.obs_password` resolves `obs.password` from the YAML if set, else falls back to
`os.environ[obs.password_env]` — this is the env-var override the README refers to.

`cfg.save_field(section, key, value)` surgically rewrites a single key in
`config.yaml` without disturbing the rest of the file — used by the setup wizard/flow
to persist `stream_id`, `ingestion_address`, and the OBS password.

### `config/games.yaml`

- `games:` — `exe.exe → {name, scene, blurb}` hand overrides for exes the public index
  gets wrong or doesn't know
- `blocklist:` — exes that must never be treated as a game (launchers, anticheat,
  browsers, wallpaper engines); supports `fnmatch` globs
- `never_stream_if_running:` — a veto list (password managers, `*banking*` glob); if
  any matching process is running, **no** game is considered at all, for the whole
  session

### `config/apps.yaml`

A separate catalogue (owned by `catalog.py`) of launchable apps discovered from
Steam/Epic/Start-Menu, each with a `stream: bool` flag controlling whether "Open &
stream" is offered on the dashboard. Distinct from `games.yaml`'s detection overrides.

## 5. CLI commands

| Command | Function | What it does |
|---|---|---|
| `setup` | `cmd_setup` → `setup_wizard.run()` | Interactive console setup: client secret → OAuth → permanent stream → OBS config → game-index/library scan → smoke test |
| `auth` | `cmd_auth` | Re-runs OAuth only (`YouTube.authorise(interactive=True)`) |
| `refresh` | `cmd_refresh` | Forces `GameIndex.refresh(force=True)` + reload |
| `scan` | `cmd_scan` | Rebuilds `config/apps.yaml` via `catalog.discover_all()`, preserving existing `stream`/`scene`/`favourite` choices |
| `detect` | `cmd_detect` | Detection-only loop, no OBS/YouTube calls; on Ctrl-C lists unindexed exes seen 60s+ for `games.yaml` triage |
| `obs-test` | `cmd_obs_test` | Creates a private test broadcast, binds it, starts OBS, polls ingestion, holds 30s if active, tears down |
| `voice` | `cmd_voice` | Checks the Kokoro voice model, `--download`s it (177 MB), `--list-voices` grouped by accent, `--sample`s every voice to wav, or `--say`s one line |
| `run` | `cmd_run` | The daemon (see §1). Accepts `--no-panel` |
| `status` | `cmd_status` | Prints `State.load()` as JSON: phase, broadcast id/URL, game, session info, paused, quota spent/left |
| `stop` | `cmd_stop` | `Engine(cfg.load()).force_stop("cli stop")` |

Global flags: `-v/--verbose`, `-q/--quiet`.

## 6. Safety mechanisms

All gating is centralized in `Engine._preflight()`, called from `_tick_idle` and
`_tick_arming`.

- **`abort_grace`** — implemented as the TESTING phase: after ingestion is confirmed,
  the broadcast is set to YouTube's `testing` (private) status rather than `live`
  immediately; a toast fires; only after `abort_grace` seconds does `_go_live()` flip
  it to `live`. `0` skips straight to live.
- **Kill switch** (`Ctrl+Alt+Shift+K` default) — global hotkey via the `keyboard`
  package, bound to `engine.submit("kill")`. `Engine.kill()` sets `state.paused`
  and calls `force_stop(..., suppress=False)`; it is deliberately **not**
  `toggle_pause`, which parks a stream on a card rather than ending it — a kill
  switch that leaves you broadcasting is not a kill switch. `state.paused` is
  also checked every LIVE tick and blocks new starts in `_preflight()`.

  **`suppress=False` is load-bearing.** `force_stop` normally marks every open
  game "do not restart", because a human pressing End stream means "stop
  streaming THIS" — and that flag is only cleared when the game exits. Pause
  borrowed the same path, so pausing ended the stream and Resume then did
  nothing at all: the only way out was to close the game or restart AutoStream.
  Pausing is temporary by definition, so it does not suppress, and `_resume()`
  additionally clears any `stopped` intent and re-arms the watcher — which also
  digs out anyone already stuck in that state.

  Pausing a LIVE session no longer ends the broadcast: OBS keeps sending the
  be-right-back card, so YouTube keeps receiving frames and the URL, the chat
  and the audience survive. See "Screen savers, and what they did to pause" and
  "The same three controls when nothing is being broadcast" above for the two
  fallbacks — no card configured, and recording-only.
- **`NOSTREAM` file** — `Engine._paused()` checks for `paths.ROOT / "NOSTREAM"` every
  tick; if present, `_preflight()` fails immediately and any LIVE session is ended.
  Just an empty file, no config needed.
- **`quiet_hours`** — `Engine._in_quiet_hours()` parses the `HH:MM` window (handles
  midnight wraparound) and is checked in `_preflight()` **unless** an explicit "Open &
  stream" click passes `force=True` — this convenience guard can be bypassed, unlike
  the hard safety checks below.
- **`never_stream_if_running`** — loaded into `GameIndex.veto_patterns`; if any
  matching process is found, `Watcher.active_game()` returns `None` unconditionally,
  vetoing the entire detection session regardless of what game is actually running.
- **AC power / disk space / quota headroom** — also checked in `_preflight()`; disk
  and quota checks are never bypassed even with `force=True`.
- **Orphan sweep on startup** — `Engine._recover()` + `youtube.sweep_orphans()`
  completes any broadcast left `active`/`testing` after an unclean shutdown.
- **Debounce** — `arm_delay` and `switch_delay` prevent alt-tab flicker from spamming
  session starts or retitles.

## 7. Notable functions by module

- **catalog.py** — `App` dataclass; `discover_steam()` (registry + `libraryfolders.vdf`);
  `discover_epic()` (`.item` manifests); `discover_shortcuts()` (Start Menu `.lnk` via
  `win32com.client`); `discover_all()` merges all three, steam > epic > shortcut;
  `launch(app)` spawns detached so the game outlives AutoStream; `is_helper(name)`
  filters installers/updaters (exempts UE `-Shipping.exe`).
- **gameindex.py** — `GameHit` dataclass; `GameIndex` merges `games.yaml` > Discord
  detectable-apps > Steam applist, caches to `index.cache.json`;
  `lookup()`/`is_blocked()`/`is_veto()`/`steam_name()`/`coverage_warning()`.
- **titles.py** — `SafeDict` (tolerant `str.format_map`); `build_vars()` assembles
  template variables; `render_title`/`render_description` apply templates with
  word-boundary truncation; `pick_hook()` picks a random flavour line.
- **notify.py** — `toast()`, always logs regardless of whether `winotify` is present.
- **panel.py** — `ControlPanel` (tkinter HUD, `refresh()` self-reschedules via
  `root.after`); `Button` (custom flat hover button — Windows ttk can't do dark
  backgrounds reliably).
- **tray.py** — `Tray` wraps `pystray.Icon` on its own thread; `_icon_image()` draws a
  colored dot per phase via Pillow.
- **web.py** — legacy standalone dashboard server; superseded, not used by `cmd_run`.
- **webui.py** — `is_configured()` gates setup-wizard vs. dashboard; `Server`
  (`ThreadingHTTPServer`) serves one HTML page toggling client-side, routes
  `/api/status`, `/api/cmd`, `/api/chat`, `/api/launch`, `/api/apps/scan`,
  `/api/theme`, `/api/setup/*` (delegates to `SetupFlow`); requests are token-authed
  via `hmac.compare_digest`.
- **window.py** — `MainWindow` (pywebview wrapper): never hide from inside the
  `closing` event handler (infinite-loop risk); only `request_quit()` may truly close
  the window (wired to tray Quit + SIGINT), with a veto-flood backstop so the user
  can't get stuck.
- **theme.py** — `THEMES` dict (midnight/carbon/ember/forest/daylight palettes);
  `css_vars()`/`listing()` render CSS and theme-picker metadata.
- **ui_assets.py** — raw `CSS`/`BODY`/`JS` strings for the dashboard + wizard,
  imported by `webui.page()`.
- **paths.py** — `ROOT` resolves from `AUTOSTREAM_HOME` env var if set, else the
  package's parent directory — this is what lets a packaged/PyInstaller build (see
  `autostream.spec`) relocate cleanly; `ensure_dirs()` creates `config/`, `secrets/`,
  `logs/` on demand.
- **setup_flow.py** — `SetupFlow`: `snapshot()`, `save_client_secret()`,
  `authorise()`, `test_obs()`, `save_section()`, `scan()`/`save_apps()` (also seeds
  `games.yaml` for streamable apps), `finish()` (creates/reuses the permanent stream,
  pushes it to OBS, refreshes the game index).
- **setup_wizard.py** — `run()` drives
  `step_client_secret → step_auth → step_stream → step_obs → step_index → step_smoke_test`.
  `step_index()` only auto-adds an exe to `games.yaml` if it's already in the public
  index or is an Unreal `-Shipping.exe` binary — it deliberately does not guess by
  "biggest exe in folder", and reports unidentified folders for manual triage.
  `step_smoke_test()` creates a private broadcast, streams via OBS, and tears down
  regardless of outcome.

## 8. External integrations

- **Windows process/window APIs** (`pywin32`) — `watcher.foreground_pid()` uses
  `GetForegroundWindow`/`GetWindowThreadProcessId` to find the focused process.
- **Windows Registry** (`winreg`) — `watcher.steam_running_appid()` reads
  `HKCU\Software\Valve\Steam\RunningAppID`; `catalog.py`/`setup_wizard.py` read
  `SteamPath`/`InstallPath` to locate Steam library folders.
- **`psutil`** — process enumeration and battery status, used throughout.
- **Steam Web API** (`ISteamApps/GetAppList`, unauthenticated) — appid→name table for
  resolving `RunningAppID`.
- **Discord detectable-apps endpoint** (unauthenticated) — primary source for the
  public exe→game-name index; parsed tolerantly to survive schema drift.
- **Epic Games Launcher manifests** — local JSON under
  `%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests`, no network call.
- **Start Menu `.lnk` shortcuts** via `win32com.client` (`WScript.Shell`).
- **`pywebview`** (Edge WebView2) — native dashboard window.
- **`pystray` + `Pillow`** — tray icon.
- **`winotify`** — toast notifications.
- **`keyboard`** — global kill-switch hotkey.
- **Google OAuth / YouTube Data API v3** — OAuth, quota accounting, broadcast
  lifecycle, chat (`youtube.py`).
- **`obsws-python`** — OBS WebSocket v5 client (`obs.py`).

No telemetry, analytics, or cloud storage integrations exist beyond the above.

## 9. On-disk layout

```
config/config.yaml       all settings
config/games.yaml        exe -> game name overrides, blocklist, veto list
config/apps.yaml         launchable-app catalogue for the dashboard (catalog.py)
config/index.cache.json  auto-downloaded public game index (gameindex.py)
config/clip_profiles.yaml  calibrated kill-marker profiles (clips/profiles.py)
config/clip_templates/     the marker patches those profiles point at (.npy)
secrets/client_secret.json
secrets/token.json       written on first auth — do not share
state.json               current phase, broadcast id, quota spend (crash recovery)
logs/autostream.log      rotating, 7 days
autostream.spec          PyInstaller build spec
```

Video and everything describing it lives under `paths.VIDEO_HOME` —
`Videos\AutoStream`, overridable with `AUTOSTREAM_VIDEO_HOME`:

```
<VIDEO_HOME>/
    2026-08-19 05-15-45.mp4  recordings (record.directory points OBS here)
    history.jsonl            one line per finished session (history.py)
    models/kokoro/           the optional voice model (paths.MODELS_DIR)
    clips/<date>_<time>_<Game>/
        session.json         source, options, every kill timestamp found
        clips.json           what was actually produced
        clips/ vertical/ montage/
```

**None of this may live under `ROOT`.** For a frozen build `ROOT` is
`dist\AutoStream`, and PyInstaller deletes that directory wholesale on every build —
`history.jsonl` and `clips/` were originally placed there and a routine rebuild
destroyed a session's history along with every clip cut from it. Recordings are also
tens of gigabytes and should survive reinstalling the app. AutoStream never deletes
any of it.
