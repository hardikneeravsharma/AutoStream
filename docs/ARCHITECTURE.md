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
| [`obs.py`](../autostream/obs.py) | obs-websocket v5 client wrapper: connect/launch OBS, configure stream service, start/stop, scene switching, health |
| [`youtube.py`](../autostream/youtube.py) | YouTube Data API v3 wrapper: OAuth, quota accounting, reusable-stream + broadcast lifecycle, chat, orphan sweep |
| [`titles.py`](../autostream/titles.py) | Pure string templating for stream title/description |
| [`notify.py`](../autostream/notify.py) | Windows toast notifications (no-ops if `winotify` missing) |
| [`catalog.py`](../autostream/catalog.py) | Discovers launchable apps (Steam/Epic/Start-Menu) for the dashboard's "Open"/"Open & stream" buttons; stored in `apps.yaml` |
| [`panel.py`](../autostream/panel.py) | Tkinter always-on-top overlay HUD (phase, timer, Stop/Pause) |
| [`tray.py`](../autostream/tray.py) | System tray icon with status menu |
| [`window.py`](../autostream/window.py) | Native app window via pywebview, falls back to default browser |
| [`webui.py`](../autostream/webui.py) | Current stdlib HTTP server: themed dashboard + first-run setup wizard (JSON API + HTML) |
| [`web.py`](../autostream/web.py) | **Legacy** — an older dashboard server, superseded by `webui.py`; not wired into `cmd_run` |
| [`setup_flow.py`](../autostream/setup_flow.py) | Backend actions for the browser-based setup wizard |
| [`setup_wizard.py`](../autostream/setup_wizard.py) | Original console/interactive setup flow (`autostream setup`) |
| [`theme.py`](../autostream/theme.py) | Named CSS colour-variable sets for the web UI |
| [`ui_assets.py`](../autostream/ui_assets.py) | Raw CSS/HTML/JS for the themed dashboard |
| [`paths.py`](../autostream/paths.py) | Single source of truth for on-disk locations; `AUTOSTREAM_HOME` override |

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
| `youtube:` | `privacy` (`unlisted` recommended initially), `latency`, `category_id`, `stream_id`/`ingestion_address` (written by setup — the permanent reusable stream), `made_for_kids`, `switch_policy` (`rolling` / `new_broadcast`) |
| `obs:` | `host`/`port` (4455), `password`, `password_env` (`AUTOSTREAM_OBS_PW`), path to `obs64.exe`, `default_scene`, `overlay_source`, `service_mode` |
| `timing:` | `poll_interval`, `arm_delay`, `abort_grace`, `switch_delay`, `cooldown`, `ingestion_timeout`, `max_session_hours`, `index_refresh_days` |
| `rules:` | `quiet_hours` (`[start, end]` as `HH:MM`), `require_ac_power`, `min_free_disk_gb`, `kill_switch_hotkey`, `paused_flag_file` (`NOSTREAM`), `quota_reserve`, `tray_icon`, `web_token` (dashboard auth token) |
| `title:` | `template` (placeholders like `{game} {hook} {day}`), `hooks` (rotating flavour text), `max_len`, `fallback_game` |
| `description:` | `template`, `tags` |
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
  package, bound to `engine.submit("toggle_pause")`. `Engine.toggle_pause()` flips
  `state.paused` and, if now paused, immediately `force_stop("kill switch")`.
  `state.paused` is also checked every LIVE tick and blocks new starts in
  `_preflight()`.
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
secrets/client_secret.json
secrets/token.json       written on first auth — do not share
state.json               current phase, broadcast id, quota spend (crash recovery)
logs/autostream.log      rotating, 7 days
autostream.spec          PyInstaller build spec
```
