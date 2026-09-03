# CLAUDE.md

Working rules for Claude Code — and any other agent or contributor — on AutoStream.
Nothing here is style advice; each rule is something that has already cost a session.

For what the app *is*, read [README.md](README.md). For how it is put together, read
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the module map there is kept current and
is the fastest way to find the file you want.

## Orientation

| Path | What lives there |
|---|---|
| `autostream/` | The package. `engine.py` is the state machine — the only place a broadcast starts, retitles or stops. |
| `autostream/clips/` | Optional clip production (numpy + ffmpeg, imported lazily behind `clips.available()`). |
| `autostream/ui/` | The dashboard: one module per page, plus `css.py`, `icons.py`, `shell.py`. |
| `config/` | `config.example.yaml` is tracked and documents every key. `config.yaml` is **not** tracked. |
| `scripts/` | `install.ps1`, `build.ps1`, `make_icon.py`, `make_zip.py`, `configure_recording.py`. |
| `tests/` | pytest — no network, no OBS, no account. |
| `docs/` | Architecture and plan notes. |

Version lives in one place: `__version__` in [autostream/__init__.py](autostream/__init__.py).

## Commands

Windows, Python 3.12+, PowerShell. Always use the venv interpreter — the system one is
missing every dependency.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # creates .venv
.\.venv\Scripts\python.exe -m pytest -q                        # the whole suite
.\.venv\Scripts\python.exe -m autostream detect                # detection only: no API, no OBS
.\.venv\Scripts\python.exe -m autostream run                   # the daemon
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Dist
```

`build.ps1 -Dist` strips every credential and verifies the zip entry by entry. Use it
for anything that leaves this machine.

## Never commit

- `config/config.yaml` — OBS websocket password, YouTube stream key, local web token.
- Anything under any `secrets/` directory — the Google OAuth client, the stored token,
  the StreamElements JWT.
- `logs/`, `state.json`, `history.jsonl` — runtime state and personal session history.
- `config/clip_profiles.yaml` — profiles calibrated on someone's own footage.
- `.claude/settings.local.json` — machine-specific permission grants.

`.gitignore` already covers all of these and explains why next to each entry. **The repo
is public.** Look at what is actually staged before committing; never force an ignored
file in with `git add -f`, and never paste a real token, stream key, channel id or
absolute home-directory path into code, a test fixture, a commit message or a PR body.
Use placeholders.

## A fix is not delivered until it is running

Every fix reaches three places, without being asked:

1. **`main`** — committed and pushed.
2. **A new GitHub release** — bump `__version__`, build with `-Dist`, tag, publish, then
   download the asset back and check its hash.
3. **The local `dist\AutoStream` build** — rebuilt and restarted, so the app in use has it.

Say plainly which of the three each fix has reached. "Pushed" does not mean "shipped" —
a fix living only on a branch while the installed build is days old is how the same bug
gets reported twice.

`main` is protected, so the version bump rides along in the open PR rather than going
straight in.

## One open PR at a time

There should never be more than one open PR. Fold a new fix into the existing one — or
cut a fresh branch from `main`, merge the outstanding fix branches into it, and open a
single PR whose body has a section per fix: what was wrong, why, and the evidence. Close
the superseded PRs with a comment pointing at the new one, and delete their branches once
merged.

Seven stacked PRs once conflicted with each other every time `main` moved, each needed
its own approval, and fixes sat unshipped while they were reviewed one at a time. One PR
is one approval and one thing to read.

## The running app is the build, not the repo

The AutoStream that is actually streaming is `AutoStream.exe` in `dist\AutoStream\`. It
reads its **own** `dist\AutoStream\config\config.yaml`, `dist\AutoStream\secrets\` and
`dist\AutoStream\logs\autostream.log` — not the repo copies. Editing the repo's
`config\config.yaml` has no effect on a live session.

To change a live setting, POST to the daemon's own API:

```
POST http://127.0.0.1:8787/api/settings/save?k=<rules.web_token>
     {"values": {"<dotted.path>": value}}
```

That endpoint is the only caller of `cfg.refresh_in_place`; writing the YAML by hand
leaves the running process on its startup config until it restarts. Read values back
from `/api/settings/values`, and read the **build's** log when diagnosing a real session.

The build fails while `AutoStream.exe` is running. Ask it to quit with
`POST /api/cmd {"command":"quit"}` — that works even when the process is elevated and
`Stop-Process` is denied. Check `/api/status` first for the phase, `recording`, and a
running clips job: quitting destroys a clip job in progress and ends a live broadcast.
Say so rather than silently killing either.

Since v1.6.5 the build preserves the live install itself — config, secrets, logs and
`state.json` are copied out before PyInstaller runs and restored afterwards. Do **not**
hand-restore config after a build; that backup is older than what the app has, so
copying it back is now the thing that loses settings. Look for
`[ok] restored the live install's ...` in the build output instead.

## Clip bugs are measured, never read

When clips come out wrong, do not read the detector looking for the bug. Build a scoring
harness and measure the output against ground truth:

- **Counter-Strike** — the `.dem` is ground truth. `cs2_demo.pick_demo()` then
  `rounds.from_demo()` gives exact round starts, kills and labels; compare the screen
  path against it round by round.
- **Valorant** — no demo exists, so ground truth is the clips a human has watched. The
  filename carries the claim (`_2kills_43m43s_`), and which ones are wrong is a labelled
  test set.
- Dump the raw readings once (`hud.scan`, `killfeed.scan`, `valorant_feed._span`) to a
  scratch directory and iterate offline. A full Valorant scan is ~7 minutes and a CS2
  kill-feed pass ~6 — re-running either per idea is unaffordable.
- Settle a disputed frame by eye: `ffmpeg -ss T` cropped to the profile's band, then
  read the PNG.

Reading the code has already missed problems that measurement found in minutes,
including a branch whose bytecode proved it was unreachable. Also check what the app
actually *used* — a re-cut reuses cached kills, so a fixed detector can still produce
old clips. Keep the harness scripts and re-run them after any detector change.

## Every detector must set itself up for a stranger

The app ships publicly, so every built-in profile is someone else's starting point.
Never assume the developer's own in-game name, HUD colour or HUD scale.

- Have each profile declare what it needs, and check that **before** a clip job starts
  rather than failing mid-scan.
- Prompt once on first use for that game, persist to `games.yaml`, never ask again.
- Prefer **measuring** over asking — sample the user's own recording and propose the
  value (HUD colour from the kill-card outline, candidate names from feed OCR). Ask only
  for what cannot be measured.
- Best of all is needing nothing: the Valorant `feedbar` detector finds the player by
  the colour the game draws around their own row, so it needs no configuration at all.
  Aim for that.

Optional extras (the Kokoro voice, `demoparser2`, Tesseract) may already be installed on
a given machine even though the docs present them as downloads. Check first — e.g.
`python -m autostream voice --list-voices` — rather than proposing a fetch that is
already on disk.

## Editing conventions

- Make source edits with the Edit tool, not `sed`. `sed` silently no-ops when a pattern
  drifts, has no read-before-edit check, and hides the diff from the editor's review
  pane. `sed` is fine for *reading* (`sed -n '10,20p'`).
- Match the surrounding code: this codebase comments the *why*, not the *what*, and the
  README and architecture docs are written in the same voice. Keep both true when
  behaviour changes.
- Tests must not need the network, OBS, or a YouTube account.

## Local Claude settings

`.claude/settings.json` is the shared, checked-in configuration. Personal grants — and
anything that widens permissions — belong in `.claude/settings.local.json`, which is
gitignored and takes precedence over the shared file. Never commit a permissive default
mode into the shared file: it would apply to everyone who clones a public repo.
