# Onboarding: your first week on AutoStream

This is the reading order and the habits. It points at the other docs rather than
repeating them, so when this and one of them disagree, **the other doc wins** -- then
fix this one.

## 1. What you are working on

AutoStream is a Windows app (with a clips-only Mac build) that does two jobs:

- **Goes live without being touched.** It watches for a game, starts OBS, creates the
  broadcast, retitles it and stops it. `autostream/engine.py` is the state machine, and
  the *only* place a broadcast starts, retitles or stops.
- **Cuts clips and reels from recordings.** It finds kills (and, for Counter-Strike,
  rounds) by reading the screen, a demo file, a match record or the audio, then cuts
  clips and builds music-synced reels. This lives in `autostream/clips/` and is
  surfaced in the Studio and Clips pages under `autostream/ui/`.

Read, in this order:

| Doc | Why |
|---|---|
| [README.md](../README.md) | What the app is, from a user's side |
| [CLAUDE.md](../CLAUDE.md) | The working rules. Each one has already cost a session |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The module map -- the fastest way to find a file |
| [ROADMAP.md](ROADMAP.md) | What is being worked on, in what order, and what has landed |
| [TESTING-UI.md](TESTING-UI.md) | How the browser tests run |
| [CLIPPING.md](CLIPPING.md), [PROGRESS.md](PROGRESS.md) | Detector background and measurements, when you touch clips |

`CLAUDE.md` is written for agents but binds every contributor. Read all of it, once,
before your first commit.

## 2. Set up

Windows, Python 3.12+, PowerShell. **Always use the venv interpreter**; the system
Python is missing every dependency.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1     # creates .venv
.\.venv\Scripts\python.exe -m pytest -q                          # the offline suite
.\.venv\Scripts\python.exe -m autostream detect                  # detection only: no API, no OBS
.\.venv\Scripts\python.exe -m autostream run                     # the daemon
```

If the offline suite is not green on a fresh checkout, stop and say so before changing
anything.

Config: `config/config.example.yaml` is tracked and documents every key.
`config/config.yaml` is **not** tracked -- it holds an OBS password, a stream key and a
web token.

### The repo is public

Never commit: `config/config.yaml`, anything under a `secrets/` directory, `logs/`,
`state.json`, `history.jsonl`, `config/clip_profiles.yaml`,
`.claude/settings.local.json`. `.gitignore` covers all of them -- never `git add -f`
around it. Look at what is staged before every commit, and use placeholders, never a
real token, stream key, channel id or home-directory path, in code, fixtures, commit
messages or PR bodies. Stage explicit paths, not `git add -A`: more than one session
can be working in the same tree.

### The running app is not the repo

The AutoStream that is actually streaming is `dist\AutoStream\AutoStream.exe`. It reads
its **own** `dist\AutoStream\config\`, `secrets\` and `logs\`. Editing the repo's config
changes nothing for a live session, and you read the *build's* log when diagnosing a
real one. Live settings change through the daemon's API (`POST /api/settings/save`), as
described in CLAUDE.md.

## 3. How the roadmap is used

[ROADMAP.md](ROADMAP.md) is the project's memory. Its own opening line is the contract:
*a session starting cold reads this file and CLAUDE.md and needs nothing else to carry
on.*

### Reading it

| Section | What it tells you |
|---|---|
| **The strategic position** | Why the order is what it is -- what the app owns, matches, and trails on |
| **The order** | Work in priority order, newest priority first. The `TOP PRIORITY` heading is what to pick up unless you were told otherwise |
| **State of the tree** | Current version, what `main` is, open PRs, and warnings about the working tree. Read it before you touch git |
| **What is not finished** | Loose ends that no table holds |
| **Progress** | One row per feature that landed, newest first |

Work is tracked in **tables of IDs** (`F1`..`F19`, `R1`..`R14`, `K1`..`K5`, `D1`..`D4`,
`M1`..`M6`, `T1`..`T5`...). Each row has a change, the **evidence** that justified it
(measured numbers, not opinion), and a **status**. Reference work by ID in commits and
PRs. Statuses are written precisely -- `done (v1.77.3)`, `partly`, `not started`,
`waiting on F18`, `needs a decision` -- and a `partly` row says what is left.

### Writing it

A roadmap nobody updates is worse than none, because the next session trusts it. So:

1. **Before starting a feature**, read the roadmap and find its row. If there is none,
   add one (with the evidence) before you build.
2. **When it lands**, in the same PR:
   - set its status in the phase table (`done (vX.Y.Z)`, or `partly` plus what is left);
   - add a row at the top of **Progress**: date, item, what landed, and -- the column
     that matters -- **what it changed about the plan**;
   - if the work changes the version, say which release carries it.
3. **Say what you learned, not only what you built.** If the estimate was wrong, or the
   order turned out wrong, say so and change the order. The Progress table is full of
   rows like "two of the three could not be built as written, and saying so was the
   work." That is the standard.
4. **Fold duplicates** into one row rather than tracking the same thing twice, and note
   in Progress that you did.
5. If **State of the tree** is no longer true after your work (version, `main`, open PRs,
   a dirty tree), fix it.

Anything that changes how a control *behaves on screen* waits for a yes from the
product owner before it is built; the roadmap marks which rows those are.

## 4. How we test

There is no single "run the tests" command. There are **seven tiers**, from cheapest to
most expensive, and `scripts\verify.ps1` runs them in order. Tests never need the
network, OBS or an account unless the tier says so.

| Tier | Marker | Needs | Asks | Time |
|---|---|---|---|---|
| 1-3 | *(none; the default)* | Nothing | Units, flows, the engine state machine against fakes | ~1 min |
| 4 | `media` | The sample-footage corpus (`AUTOSTREAM_TESTDATA`, default `C:\autostream-testdata`) | Real detectors on real recordings, scored against a reviewed baseline; real encodes | 10-40 min |
| 5 | `build` | `dist\AutoStream\AutoStream.exe` | The built binary boots and answers over HTTP -- catches PyInstaller packaging breakage no offline test can see | minutes |
| 6 | `live` | Real OBS, a real YouTube account | Creates and deletes a real private broadcast. Costs quota; never unattended; needs `-Live` | -- |
| 7 | `ui` | The build and Playwright + Chromium | The built app in a real browser: console errors, refused requests, media that really plays | ~15 min |

`pytest.ini` excludes tiers 4-7 by default (`-m "not media and not build and not live
and not ui"`), so a plain `pytest -q` runs only the offline suite -- **and says nothing
about the rest**. A green `pytest -q` is not a verified release.

### While you work

```powershell
.\.venv\Scripts\python.exe -m pytest -q                          # offline suite
powershell -ExecutionPolicy Bypass -File scripts\verify.ps1 -Quick   # tiers 1-3, ~25 s
```

If you touched the dashboard or any page, a browser has to press the button.
`docs/TESTING-UI.md` has the detail; the short version:

```powershell
$env:AUTOSTREAM_VERIFY_SOURCE = "1"      # run this checkout, no build needed
.\.venv\Scripts\python.exe -m pytest tests\verify\test_ui_sweep.py -m ui -q -p no:randomly
```

Why this is non-negotiable: `clip_show` is a class toggle, so a control that is
unreachable, invisible or wired to nothing passes every unit test there is. Several
bugs got through 2,200 passing tests and were caught the moment a browser pressed the
button. **Never conclude a UI works from reading its JavaScript.**

### Before every release

`scripts\build.ps1 -Dist` is the release gate. It runs `verify.ps1` first and **will
not build if it fails**; a plain `build.ps1` runs only the quick offline tiers.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Dist -HandOff
```

What happens, in order:

1. **Tiers 1-3** (offline) -- every time.
2. **Tier 4** (clip detectors on real footage) -- **only if something it measures
   changed**. `verify.ps1` diffs the working tree against the last `v*` tag; if anything
   under `autostream/clips/` or tier 4's own files changed, it runs, and prints which
   files bought the wait. If nothing did, it skips and says why. Any uncertainty (no
   git, no tag) means *run it*. `-Media` / `-NoMedia` force it either way.
3. **Tier 5** (the built binary boots) and **tier 7** (the browser) -- under `-Release`.
   They need a build and need **the app not running**, or they skip.
4. **Tier 6** (real broadcast) -- only with `-Live`, never unattended.
5. The build itself: PyInstaller into `dist\AutoStream`, credentials stripped, the zip
   verified entry by entry.

Rules that go with it:

- **A skipped tier is not a passed tier.** The summary says which is which, and every
  skip names its reason. Report it that way.
- **Measure, don't read.** Detector work is judged by a scoring harness against ground
  truth (the `.dem` file for Counter-Strike; human-watched clips for Valorant), never by
  reading the code. Settle a disputed frame by eye.
- **A reader slower than real time is not shipped.** The CS2 screen read (`killfeed`)
  runs at ~1.2-1.5x real time and is developer-mode only. Anything new needs a measured
  rate; under about 5x real time it is a developer tool. Set
  `AUTOSTREAM_SLOW_READERS=1` to measure the skipped ones.
- **Nothing a test runs may open a window on the screen.** File pickers are refused by
  `AUTOSTREAM_NO_DIALOGS=1`; every `subprocess.run` you add takes
  `creationflags=appd.NO_WINDOW`.
- **Every control gets a scenario.** Add to `docs/UI-SCENARIOS.md` before adding a UI
  test, so the gaps stay countable. The sweep's `REACHED_FLOOR` only goes up.
- Tests must fail when the thing is broken: prove a new guard against a planted
  regression (one UI test shipped for weeks comparing against `#fff` after CSSOM had
  normalised it to `rgb(...)`, and could never fail).

### Before the app is rebuilt on the maintainer's machine

Rewriting `dist\AutoStream` closes the running app for about two minutes. Check
`/api/status` first: IDLE and not recording, and `/api/studio/job` not running, means go
ahead. Anything else -- LIVE, recording, a clip job, a reel rendering -- means ask first.
`-HandOff` waits for idle and reopens the app itself. OBS must be closed too, or it holds
DLLs out of `_internal` and the build leaves a gutted install.

## 5. How a change reaches users

A fix is not delivered until it is running in **three** places, and you say plainly
which it has reached:

| # | Where | How |
|---|---|---|
| 1 | `main` | `main` is protected: the work rides in a PR, with `__version__` bumped in `autostream/__init__.py` (the only place the version lives) |
| 2 | A GitHub release | Once merged, push an annotated tag on `main`: `git tag -a vX.Y.Z -m "vX.Y.Z: title" -m "notes"` then `git push origin vX.Y.Z`. `release.yml` builds the Windows zip and installer and both macOS `.dmg`s on GitHub's runners and publishes them with `.sha256` files. The tag must match `__version__` or nothing builds. Download the assets back and check their hashes |
| 3 | The local `dist\AutoStream` | Rebuilt with `build.ps1 -Dist -HandOff` so the installed app has the fix |

CI (`ci.yml`) runs the offline suite on Windows and macOS for the PRs that touch them
(`scripts/ci_changes.py` decides which). Both checks are required, and a docs-only PR
still merges.

**One open PR at a time.** Fold a new fix into the open PR, or cut a fresh branch from
`main`, merge the outstanding fix branches into it and open a single PR with a section
per fix: what was wrong, why, the evidence. Close the superseded PRs with a pointer.

## 6. Status updates

Every time work finishes, pauses, stalls or raises a question, answer in this shape and
nothing else:

1. **Headline** -- one line saying *why you stopped* (done / blocked / waiting on you).
2. **Done** -- facts, not narrative.
3. **Pending** -- named.
4. **Blocking** -- and who unblocks it. "Nothing" is a valid answer.

Detail belongs in the commit message, PR body and roadmap row.

## 7. Conventions worth knowing on day one

- Make source edits with an editor tool, not `sed`; `sed` silently no-ops when a
  pattern drifts.
- Comment the *why*, not the *what*. Keep README and ARCHITECTURE true when behaviour
  changes.
- A detector must set itself up for a stranger: never assume the developer's in-game
  name, HUD colour or scale. Prefer measuring over asking; prefer needing nothing.
  Declare what a profile needs and check it before a job starts.
- A page must not call audio-loudness finds "kills" (`clip_found()` in `ui/clips.py`
  chooses the word).
- Optional extras (Kokoro voice, `demoparser2`, Tesseract) may already be installed;
  check before proposing a download.
- Personal permission grants go in `.claude/settings.local.json`; never commit a
  permissive default into `.claude/settings.json`.

## 8. Your first-week checklist

- [ ] Read README, CLAUDE.md, ARCHITECTURE (module map), ROADMAP (top priority,
      State of the tree, the last ten Progress rows).
- [ ] `install.ps1`, then `pytest -q` is green.
- [ ] `python -m autostream detect` runs.
- [ ] Run `verify.ps1 -Quick` and read the tier summary.
- [ ] Run one UI file with `AUTOSTREAM_VERIFY_SOURCE=1` and watch it pass.
- [ ] Open `docs/UI-SCENARIOS.md` and find one gap.
- [ ] Pick a small roadmap row with the owner, build it, land it with a Progress row.
