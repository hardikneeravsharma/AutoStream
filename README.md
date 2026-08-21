<img src="docs/img/logo.png" width="96" align="left" alt="">

# AutoStream

**Launch a game. It goes live on YouTube by itself.**

<br clear="left">


AutoStream sits quietly in your Windows system tray and watches which program has
focus. The moment you start a game it recognises, it creates a YouTube broadcast,
tells OBS to start streaming, and titles the stream after the game you are playing.
Switch to a different game and it rewrites the title. Quit the game and it ends the
broadcast and tidies up.

You set it up once. After that you never open it again unless you want to.

![AutoStream holding a broadcast private during its cancel window, with a countdown
ring reading 4 seconds and a bar warning that the stream goes public when it runs
out](docs/img/countdown.png)

> Nothing goes public by surprise. Every broadcast is held **private** behind a
> visible countdown first, with a Cancel button — that window is the whole point.

---

## What it actually does

| | |
|---|---|
| **Detects the game** | Watches the foreground window and running processes, and resolves the `.exe` to a real game name using a public index of ~10,000 titles plus your Steam library. No manual list to maintain. |
| **Starts the broadcast** | Creates the YouTube broadcast over the API, binds it to a permanent stream key, and pushes that key into OBS over websocket — you never touch OBS stream settings. |
| **Writes the title** | From a template you control, e.g. `{game} — {hook} \| {day} night stream`. |
| **Handles the switch** | Change games and it either retitles the same broadcast or starts a fresh one, your choice. |
| **Stops cleanly** | Close the game, wait out the cooldown, and it ends the broadcast. If it ever crashes mid-stream it sweeps the orphaned broadcast on next start. |
| **Records and clips** | Optionally records locally while streaming, then finds your kills in that recording and cuts them into clips, vertical versions and a montage. |

It talks to exactly three places: **YouTube** (your own channel, through your own
Google Cloud project), **your local OBS**, and two public read-only game-name lists.
There is no server, no account, and no telemetry. Everything it stores stays in its
own folder.

### The window

Closing the window does not quit — it keeps running in the tray so it can detect games.

| Page | What's on it |
|---|---|
| **Dashboard** | Live status, a countdown ring before anything goes public, viewers/likes/views with a live graph, ingest health from OBS, and live chat. |
| **Library** | Every game it found. "Open + stream" launches one and goes live deliberately. |
| **Clips** | Every stream you've recorded. Pick one, choose how busy a moment has to be, and it cuts the clips. |
| **Settings** | All 58 options as real controls, grouped, in plain language. |
| **Logs** | What it did and — more usefully — why it decided *not* to stream. |

![The AutoStream dashboard while live: session timer, watching/likes/views counters,
a viewer graph for the session, OBS ingest health, and live chat](docs/img/dashboard.png)

---

## Before you start

You need three things. The first one can take a day, so start it now:

1. **A YouTube channel with live streaming enabled.**
   youtube.com → Create → Go live. On a brand-new channel this can take **up to 24
   hours** to activate. Nothing else will work until it does.
2. **OBS Studio** — [obsproject.com](https://obsproject.com)
3. **A free Google Cloud project.** The setup wizard walks you through creating it.
   This is what gives you your own YouTube API allowance rather than sharing one.

In OBS, before you begin: **Tools → WebSocket Server Settings** → tick **Enable
WebSocket server**, leave the port at **4455**, set a password, then click **Apply**
and **OK**. OBS does not open the port until that dialog is committed.

---

## Install (the easy way)

**[⬇ Download the latest release](https://github.com/hardikneeravsharma/AutoStream/releases/latest)**

1. Download `AutoStream-share.zip` and unzip it somewhere permanent, e.g.
   `C:\AutoStream`. Do not run it from inside the zip.
2. Double-click **`AutoStream.exe`**.
   Windows SmartScreen will warn you because the app is not code-signed —
   **More info → Run anyway**.
3. A setup wizard opens. It takes about ten minutes, most of it waiting on Google.

No Python needed. The zip contains no accounts or keys; you connect your own channel
during setup.

### Two things people get wrong

> **Publish your OAuth consent screen.**
> Google Auth Platform → **Audience** → **Publish App**. If you leave it in *Testing*,
> your login silently expires after about 7 days and streaming stops with an
> `invalid_grant` error. You do **not** need Google's verification review.

> **"Google hasn't verified this app" is expected.**
> It is your own personal app. Click **Advanced → Go to … (unsafe)**.

### Start it automatically at login

Finish the wizard first, then open PowerShell **as Administrator** and run:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\AutoStream\Run-At-Startup.ps1"
```

It registers a Scheduled Task that starts AutoStream 45 seconds after every login,
then starts it immediately and confirms it is actually running. Add `-Remove` to undo.

Administrator is needed only to *register* the task. AutoStream itself runs as you —
it has to, because a service cannot see your desktop, your games, or OBS.

---

## Your first week

Leave **privacy on `unlisted`** (the default) until you trust it. Watch a few
sessions, confirm it detects your games correctly, then switch to public in
**Settings → Stream**.

> **Use a Game Capture scene in OBS, never Display Capture.**
> If detection is ever wrong, viewers see a black screen instead of your desktop,
> your email, or whatever else is on your monitor.

### Safety rails, all on by default

| Rail | What it does |
|---|---|
| **Cancel window** | 20 seconds held privately before anything goes public, with a desktop notification and a Cancel button on the dashboard. |
| **Kill switch** | `Ctrl+Alt+Shift+K` pauses everything and stops the stream, from inside any game. |
| **`NOSTREAM` file** | Create an empty file called `NOSTREAM` next to the exe and nothing will ever auto-start. Delete it to re-enable. |
| **Arm delay** | A game must stay open 30 seconds before anything happens, so alt-tabbing never triggers a stream. |
| **Quiet hours** | Optional window where it never auto-starts. Off by default; set it in Settings → Safety. |
| **Veto list** | If a password manager or banking app is running, the entire session is vetoed and nothing streams. |
| **Battery / disk / quota** | Won't start on battery, with under 25 GB free, or when your API quota is nearly spent. |

---

## Install from source

For development, or if you would rather not run a downloaded binary.

Requires **Python 3.12+** and Git.

```powershell
git clone https://github.com/hardikneeravsharma/AutoStream.git
cd AutoStream
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

That creates `.venv` and installs dependencies. Then run it — with no config present
it opens the same setup wizard:

```powershell
.\.venv\Scripts\python.exe -m autostream run
```

`config/config.yaml` is **not** tracked by git — it holds your OBS password, YouTube
stream key and local web token. You do not need to create it; the wizard writes it.
[`config/config.example.yaml`](config/config.example.yaml) documents every key.

### Recommended bring-up

Rather than going straight to `run`:

```powershell
# 1. Detection only. No API, no OBS, no streaming. Run it for an evening.
.\.venv\Scripts\python.exe -m autostream detect

# 2. Prove OBS -> YouTube works, on a private broadcast.
.\.venv\Scripts\python.exe -m autostream obs-test

# 3. The real thing.
.\.venv\Scripts\python.exe -m autostream run
```

`detect` prints every unrecognised `.exe` it saw for 60s+ when you Ctrl-C it. Sorting
those into `games:` and `blocklist:` in `config\games.yaml` is the highest-value
30 minutes you can spend — it is what makes detection feel reliable rather than random.

### Build the .exe

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1          # -> dist\AutoStream\
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Dist    # -> shareable zip, no credentials
powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1  # Desktop + Start Menu
```

`-Dist` strips every credential and verifies the archive entry by entry before writing
it. That check exists because `Compress-Archive` reports a per-file failure and then
carries on — Defender briefly locks `base_library.zip` right after PyInstaller writes it,
and a zip missing that one file produces an exe that will not start. Zipping is done by
[`make_zip.py`](scripts/make_zip.py), which retries past the lock and then verifies.

The app icon is generated, not hand-drawn — [`make_icon.py`](scripts/make_icon.py) reads
the same mark and palette token the UI uses, so the two can never drift apart. Rerun it
if you change the accent colour; do not edit the `.ico` by hand:

```powershell
.venv\Scripts\python scripts\make_icon.py       # -> autostream\ui\assets\autostream.ico
```

It writes nine sizes in three tiers. A single bitmap scaled down is what makes small
icons mush: at 16px the mark's 2.2-unit ring stroke is under one pixel, so the smallest
tier drops the outer ring and uses its own bolder proportions.

### Commands

Global flags `-v/--verbose` and `-q/--quiet` work before or after the subcommand.

| Command | What it does |
|---|---|
| `run` | The daemon: window, tray, engine. |
| `setup` | Console setup wizard (the windowed one is easier). |
| `detect` | Detection only — no API, no OBS, no streaming. |
| `obs-test` | 30-second private test stream end to end. |
| `status` | Print current phase, broadcast URL and quota spend as JSON. |
| `stop` | Force-stop whatever is live right now. |
| `scan` | Re-scan for installed games and apps. |
| `auth` | Re-run the Google login if the token ever breaks. |
| `refresh` | Force a game-index refresh. |

---

## How it works

Full technical reference: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

### Themes

![The five built-in themes — Midnight, Carbon, Ember, Forest and Daylight — each
shown as a four-colour swatch](docs/img/themes.png)

Every colour in the app resolves through one token contract in
[`theme.py`](autostream/theme.py), so a theme is a palette definition and nothing
else — no view needs to know a theme exists.

### The state machine

Everything is driven by one loop in [`engine.py`](autostream/engine.py), ticking every
3 seconds. It is the only place a broadcast is ever started, retitled or stopped.

```
IDLE ──▶ ARMING ──▶ STARTING ──▶ TESTING ──▶ LIVE ──▶ COOLDOWN ──▶ STOPPING ──▶ IDLE
  │         │                       │                    │
  │         │                       │                    └─ game switch: retitle, or
  │         │                       │                       start a fresh broadcast
  │         │                       └─ the cancel window: private, and
  │         │                          abortable, before it goes public
  │         └─ the game must survive 30s here, so alt-tab never triggers a stream
  └─ preflight: paused? quiet hours? on battery? disk? quota? veto list?
```

State is written to `state.json` **before** each side effect, so a crash mid-transition
is always recoverable — on next start it sweeps any orphaned broadcast.

### Recording and clips

Turned **off** by default, because it costs disk. Switch it on in **Settings → Recording**.

**Why record at all when YouTube already keeps a VOD?** Because that VOD is a copy of a
copy. OBS sends 1080p60 at 10 Mbps, YouTube re-encodes it to roughly 4.5, and Studio
hands back a 720p transcode of *that*. Every clip cut from it starts two lossy
generations down. Recording writes the same picture straight to disk while you stream,
which costs no game framerate on a GPU with a dedicated encoder.

Budget roughly **20–30 GB per hour** at Indistinguishable quality. **AutoStream never
deletes a recording.** Below `record.min_free_gb` it declines to record and streams
anyway rather than making room for itself.

One helper configures OBS for this, and verifies it rather than assuming:

```powershell
.venv\Scripts\python scripts\configure_recording.py            # apply
.venv\Scripts\python scripts\configure_recording.py --dry-run  # just look
.venv\Scripts\python scripts\configure_recording.py --revert   # undo
```

It sets recording to NVENC at CQP ~16, points it at `Videos\AutoStream`, and splits the
audio into **three tracks — 1 the mix, 2 your mic alone, 3 game and Discord alone** — so
a mic that was too quiet can be fixed afterwards in an editor instead of being baked in.
Then it records for five seconds and runs `ffprobe` over the result to prove the tracks
actually landed.

**Finding the kills.** Most shooters confirm your own kill with a fixed glyph on the HUD
— Delta Force draws a skull under the crosshair. That is much better to detect than the
kill feed, which lists everyone's kills and needs OCR plus fuzzy name matching to work
out whose. AutoStream template-matches the glyph instead. On a two-hour session that is
a 60-second scan and it found 219 kills.

Delta Force ships calibrated. Any other game takes about a minute: **Clips → Calibrate a
game**, scrub to a frame just after a kill, drag a box round the marker. It then measures
whether that patch actually stands out from the rest of the recording and tells you, and
refuses to save a template that would match everything.

**Games with no marker at all.** Counter-Strike 2 draws no kill confirmation — no
hitmarker, no banner — and announces kills only in the feed. For those, pick **Only in
the kill feed** when calibrating, drag the box round the whole feed, and give your
in-game name exactly as it appears there. AutoStream then reads the feed and works out
which slot your name is in:

```
        YUVANETA  [rifle]  ANSHU      <- one name past yours: your kill
Rico +  YUVANETA  [rifle]  ANSHU      <- still your kill; Rico assisted
YUVANETA + Rico   [rifle]  ANSHU      <- two names past yours: you assisted
wAcKyPrAnKsTeR    [rifle]  YUVANETA   <- your name last: you died
```

Assists are detected and deliberately **not** clipped, so "3 kills" in a filename means
three. Reading the feed is slower than matching a glyph — roughly a minute per ten
minutes of footage — and it needs Tesseract:

```powershell
winget install --id UB-Mannheim.TesseractOCR
pip install pytesseract
```

CS2 ships with the feed area already set; you only have to supply your name.

**What comes out**, in `clips/<date>_<time>_<Game>/`:

```
clips/     Delta-Force_01_5kills_12m48s_30s.mp4      <- the editing copies
vertical/  Delta-Force_01_5kills_12m48s_30s_vertical.mp4
montage/   Delta-Force_2026-08-19_montage_12clips_47kills_5m12s.mp4
session.json  clips.json                             <- what was found, and cut
```

Filenames repeat the game on purpose: clips get dragged into editors and uploaded, and
the folder they came from is lost the moment they are.

`Minimum kills per clip` counts kills **inside the finished clip**, not inside the fight
it came from — a five-kill fight spread over ninety seconds does not become a five-kill
twenty-second clip. Longer clips therefore find more of them:

| Minimum | 20s clips | Whole moment |
|---|---|---|
| 1+ | 88 clips, 70% of kills | 88 clips, 100% |
| 2+ | 39 clips, 47% | 45 clips, 80% |
| 3+ | 20 clips, 30% | 26 clips, 63% |

*(measured on one real two-hour session with 219 kills)*

Needs **ffmpeg** (`winget install --id Gyan.FFmpeg`) and **numpy**. Without either, the
Clips page shows what is missing and the rest of AutoStream is unaffected.

### Module map

| Module | Responsibility |
|---|---|
| [`engine.py`](autostream/engine.py) | The state machine. The only place streams start or stop. |
| [`watcher.py`](autostream/watcher.py) | Foreground window + process polling. No network. |
| [`gameindex.py`](autostream/gameindex.py) | exe → game name, from your overrides + public indexes. |
| [`obs.py`](autostream/obs.py) | obs-websocket v5 client. |
| [`youtube.py`](autostream/youtube.py) | YouTube Data API v3: OAuth, broadcasts, chat, quota. |
| [`schema.py`](autostream/schema.py) | One declarative source of truth for all 58 settings — drives both the settings form and server-side validation. |
| [`history.py`](autostream/history.py) | Append-only journal of finished sessions. The only record of which game ran on which broadcast. |
| [`clips/`](autostream/clips/) | Optional. `detect` finds kill markers, `plan` decides what to cut, `cutter` and `montage` produce the files, `jobs` runs it off the engine thread, `calibrate` teaches it a new game. |
| [`webui.py`](autostream/webui.py) | Local HTTP server and JSON API. |
| [`ui/`](autostream/ui/) | The five-page web app: `shell`, `dashboard`, `library`, `clips`, `settings`, `logs`, `setup`. |
| [`window.py`](autostream/window.py) | Native window via pywebview (Edge WebView2). |
| [`cfg.py`](autostream/cfg.py) | Config load/merge with defaults, atomic writes. |

### Threading

pywebview must own the main thread, so everything else runs beside it:

```
main    pywebview native window
worker  engine poll loop      <- the only thread with side effects
worker  HTTP server (web UI)
worker  tray icon
worker  overlay panel
worker  clip job              <- only while cutting clips
```

The UI never touches OBS or YouTube directly. It posts commands onto a queue that the
engine thread drains, which is what keeps "two clicks at once" from racing.

A clip job gets its own thread for the same reason inverted: the engine loop is strictly
serial, so a multi-minute ffmpeg pass parked in it would freeze phase transitions and the
OBS watchdog for the duration. It reports progress into the status payload the dashboard
already polls, which is also why progress survives closing and reopening the page.

### Files it writes

```
config/config.yaml         your settings (not in git — contains secrets)
config/games.yaml          exe -> name overrides, blocklist, veto list
config/apps.yaml           the launcher's app list
config/index.cache.json    downloaded game index
config/clip_profiles.yaml  kill-marker profiles you calibrated
config/clip_templates/     the marker images themselves
secrets/client_secret.json Google Cloud credentials
secrets/token.json         your YouTube login — never share this
state.json                 current phase and broadcast id (crash recovery)
logs/autostream.log        rotating, 7 days
```

Video and its metadata live **outside** the application folder, in
`Videos\AutoStream` (override with `AUTOSTREAM_VIDEO_HOME`):

```
Videos\AutoStream    2026-08-19 05-15-45.mp4    the recordings themselves
    history.jsonl              one line per finished stream — what the Clips page reads
    clips\<date>_<time>_<Game>\   finished clips, one folder per stream
```

They are kept out of the app folder deliberately. A frozen build lives in
`dist\AutoStream`, and **PyInstaller deletes that entire directory on every rebuild** —
so anything stored there is destroyed by a routine `build.ps1` run. Recordings, clips and
the session journal all outlive any particular installation, so none of them belong
inside it.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **The stream is a black screen** | Almost always kernel anti-cheat refusing OBS's Game Capture hook — Delta Force, Valorant, anything with EasyAntiCheat. **Run OBS as administrator.** The failure is silent and total: the capture stays black while streaming, recording and ingest health all report perfectly fine. Turn on **Start OBS as administrator** in Settings → OBS, and tick *Run this program as an administrator* under the exe's Compatibility tab so it applies however OBS is started. |
| **It goes live before the game is up, then flaps to Cooldown** | The game has a small launcher stub that starts the real binary and exits. Arm on the stub and you broadcast a black screen until the game loads. Add the stub to `blocklist:` in `config\games.yaml` — for Delta Force that is `deltaforceclient.exe`, leaving `deltaforceclient-win64-shipping.exe` as the game. |
| **Nothing happens when I launch a game** | It is not in the index. Check the **Logs** page to see what was detected, then add the exe under `games:` in `config\games.yaml`. |
| **It started for something that isn't a game** | Add that exe to `blocklist:` in `config\games.yaml`. |
| **A game I own isn't in the Library** | Non-Steam launchers proxy through their own client (Valorant's shortcut points at `RiotClientServices.exe`), and some Steam games hide the real binary several folders deep. Both are handled — hit **Rescan**. If it still misses, add it under `games:` in `config\games.yaml`. |
| **`invalid_grant`, or it stopped working after a week** | The OAuth consent screen is still in *Testing*. Publish it, then re-run setup or `-m autostream auth`. |
| **Can't reach OBS** | Is OBS running? WebSocket enabled? Password right? Did you click **Apply** in that dialog? |
| **Stuck on "Starting", then gives up** | YouTube is not receiving video. Confirm live streaming is actually enabled on the channel (can take 24h), then re-run setup to rewrite the stream key. |
| **Broadcast stuck live after a crash** | Restart it — it sweeps orphans on startup. Or run `-m autostream stop`. |
| **It doesn't start at login** | `Get-ScheduledTaskInfo -TaskName AutoStream`. `0x0` or `0x41301` is healthy; anything else, check `logs\autostream.log`. |
| **It won't start at all** | Read `logs\autostream.log` and `logs\crash.log` next to the exe. |

---

## Licence

[Apache License 2.0](LICENSE) — free to use, modify and distribute, including commercially,
provided you keep the notice and state your changes. Comes with an explicit patent grant and
no warranty.
