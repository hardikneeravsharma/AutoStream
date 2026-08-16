# AutoStream

Detects which game you launch on Windows, starts a YouTube live broadcast on its own,
and rewrites the title in real time as you switch games. Set up once, then forget it.

You have already done **Phase A** (YouTube channel) and **Phase B** (Google Cloud).
What follows is Phases C, D and E.

---

## Phase C — install

Put this folder somewhere permanent, e.g. `C:\autostream`. Then:

```powershell
cd C:\autostream
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

> **Cloning this repo?** `config/config.yaml` is not tracked — it holds your OBS
> password, YouTube stream key and local web token. You do not need to create it:
> the setup wizard writes it on first run. `config/config.example.yaml` documents
> every key if you would rather start from a template.

That creates `.venv`, installs dependencies, finds `client_secret.json` in your
Downloads folder and copies it to `secrets\`, and prompts for your obs-websocket
password.

**Before you run it**, open OBS → **Tools → WebSocket Server Settings**:

- tick **Enable WebSocket server**
- port **4455**
- set a password, click **Show Connect Info** to copy it

---

## Phase D — one-time setup

```powershell
.\.venv\Scripts\python.exe -m autostream setup
```

Six steps, all automatic apart from one browser click:

1. Finds/copies `client_secret.json`
2. Opens your browser for OAuth — **you will see "Google hasn't verified this app".
   That is expected.** Click *Advanced → Go to … (unsafe)*.
3. Creates your **permanent reusable ingestion stream** and saves its ID to `config.yaml`
4. Pushes the stream key into OBS over websocket (you never touch OBS stream settings again)
5. Downloads the public game index and pre-seeds `games.yaml` from your Steam library
6. Runs a 60-second **private** smoke test, then deletes it

> **Critical:** if your Google Cloud OAuth consent screen is still in *Testing* mode,
> your refresh token dies after ~7 days. Go to **Google Auth Platform → Audience →
> Publish App**. You do not need Google's verification review.

---

### Stage-by-stage bring-up (recommended)

Don't go straight to `run`. Do this instead:

```powershell
# 1. Detection only. No API, no OBS, no streaming. Run for an evening.
.\.venv\Scripts\python.exe -m autostream detect

# 2. Prove OBS -> YouTube works, on a private broadcast.
.\.venv\Scripts\python.exe -m autostream obs-test

# 3. The real thing, in the foreground, so you can watch it.
.\.venv\Scripts\python.exe -m autostream run
```

`detect` prints every unindexed `.exe` it saw for 60s+ when you Ctrl-C it. Sort those
into `games:` and `blocklist:` in `config\games.yaml`. This is the single highest-value
30 minutes you can spend — it's what makes detection feel reliable instead of random.

---

## Phase E — make it permanent

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
Start-ScheduledTask -TaskName AutoStream
```

Runs at logon + 45s via `pythonw.exe`, so there's no console window. A tray icon
shows the current phase with Pause / Force stop / Open logs.

To remove: `powershell -File scripts\register_task.ps1 -Remove`

---

## Commands

| Command | What it does |
|---|---|
| `setup` | One-time interactive setup |
| `detect` | Detection only — no streaming. Use this first. |
| `obs-test` | 30s private test stream |
| `run` | The daemon |
| `status` | Print current phase, broadcast URL, quota spend |
| `stop` | Force-stop whatever is live right now |
| `auth` | Re-run OAuth (if the token ever breaks) |
| `refresh` | Force a game index refresh |

---

## Safety rails (all on by default)

- **`privacy: unlisted`** — leave it there for the first week. Flip to `public` in
  `config\config.yaml` once you trust it.
- **`abort_grace: 20`** — 20 seconds held in testing, with a desktop toast, before
  anything goes public.
- **Kill switch** — `Ctrl+Alt+Shift+K` pauses everything and stops the stream.
- **`NOSTREAM` file** — create an empty file called `NOSTREAM` in the project root
  and nothing will ever auto-start.
- **`quiet_hours`** — never auto-start between 01:30 and 09:00.
- **`never_stream_if_running`** — password managers etc. veto the whole session.
- **Use Game Capture scenes, never Display Capture.** If detection is ever wrong,
  viewers see a black screen instead of your desktop.

---

## Layout

```
config/config.yaml     all settings
config/games.yaml      your exe -> game name overrides, blocklist, veto list
config/index.cache.json  auto-downloaded public game index
secrets/client_secret.json
secrets/token.json     written on first auth — this is your login, don't share it
state.json             current phase, broadcast id, quota spend (crash recovery)
logs/autostream.log    rotating, 7 days
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `invalid_grant` on every call | Publish the OAuth consent screen, then `-m autostream auth` |
| `could not reach obs-websocket` | OBS running? WebSocket enabled? Password matches `AUTOSTREAM_OBS_PW`? |
| Stuck in STARTING, then aborts | YouTube isn't receiving bytes. Re-run `setup` to rewrite the stream key, and confirm live streaming is actually enabled on the channel (can take 24h). |
| Stream never starts on a game | It's not in the index. Run `detect`, find the exe, add it to `games.yaml`. |
| Started for something that isn't a game | Add that exe to `blocklist:` in `games.yaml`. |
| Broadcast stuck live after a crash | Restart the daemon — it sweeps orphans on startup. Or `-m autostream stop`. |
