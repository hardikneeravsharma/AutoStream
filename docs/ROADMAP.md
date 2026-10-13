# Roadmap and progress

The order the work is being done in, why that order, and what has actually
landed. **A session starting cold reads this file and CLAUDE.md and needs
nothing else to carry on.**

Keep it current: every feature that lands gets a row in [Progress](#progress),
written the day it lands. A roadmap nobody updates is worse than none, because
the next session trusts it.

---

## Where this comes from

The order below is from **AutoStream — Market & Competitive Analysis**
(2026-10-04), a Claude doc:
`https://claude.ai/code/artifact/432b4def-2b21-4696-a94c-c93e16832f0a`

That document has the market figures, the tool-by-tool comparison and the
reasoning. This file has only the decisions and the state. Read the doc when
you need to know *why* something is ranked where it is; read this file when
you need to know *what is next* and *what is done*.

## The strategic position, in one paragraph

Of the seven jobs these tools are bought for, AutoStream **owns two** — going
live without being touched, and telling a round or a match apart from a kill.
Nothing else shipped does either. It is at **parity on two** (local recording,
vertical export) and **behind on three** (breadth of games, music editing
polish, publishing). The tension that shapes everything below: the clipping
half of the product competes with Medal, Insights and Eklipse, who are far
better funded — while the half nobody else has reaches only 24% of gaming
watch time, because it is YouTube-only.

That is why the first item is Twitch and Kick.

---

## The order

### Now — the CS2 card tally fails for an outside user (2026-10-06)

**Ahead of everything below, because a real user is blocked today.** A
friend on v1.42.0 (Radeon RX 9070 XT, 1080p60, 54-minute `.mov`) ran
*Kill tally only* and got `No kills found`. The diagnostic file and his log
gave: `measured CS2 HUD colour: hue 202 (3 tally reading(s))`, then
`5 flash(es) ... 32563 samples, 0 own emblem(s)`.

Investigated against his screenshots and a 2m43s screen recording of the same
stream (3 real kills, at ~9.8s / 37.8s / 46.9s, checked by eye). **Not the
GPU** -- `cuda: false` was detected correctly and the sweep decoded for 124s.
**Not the HUD position** -- the shipped `CARDS` / `V_BEAM` / `V_EMBLEM` boxes
land exactly on his card, beam and emblem, and one card measures 34px. With
hue 300 forced, `main`'s scanner finds **exactly the 3 kills**. Everything
went wrong at the colour.

| # | Fix | Evidence | Status |
|---|---|---|---|
| T1 | **`hud_hue` and `card_box` are never saved.** `jobs.py` switches the profile to `cardcount` in memory only; `profiles.remember()` reloads it as `killfeed` and `as_dict()` writes those keys only for `cardcount`, so both are dropped while `remember()` returns True. Every run measures from scratch, and the card-area calibration's "saved" is a lie too. Write them in any mode | Reproduced against a throwaway `AUTOSTREAM_HOME`: `remember(hud_hue=300) -> True`, file has no `hud_hue`, reload gives `0.0`. Hand-adding `hud_hue: 300.0` under `cs2.exe` **does** load | **done 2026-10-08** — written in any mode; a test on the profile CS2 really has |
| T2 | **Hue picking is fragile on long recordings.** 60 seeks across 54 min caught 3 readings, the floor (`HUE_EXACT_MIN`), and blue 202 cleared it; the 180-sample retry never ran. `best_hue()` takes the most readings, not the most reliable arc. His cards are pale lavender, saturation 0.12–0.18 on sandstone vs `SAT_MIN` 0.18, so ~30% of tally frames are unreadable at the right hue | On the sample: 60 frames → 288 ✅, every 3rd → **350 ❌**, every 6th → 290, every 10th → none. Beam saturation is ~0.25–0.40 — a better colour source than the cards | **done 2026-10-08** — two looks a second apart over a moving view, spectating set aside, a clear win or look harder (60→180→360), colour refined from the card's own pixels. See Progress |
| T3 | **Phantom kill when a pale card fades to "0".** `hidden_kills()` treats a 0 reading as a round reset, so the card coming back as 1 is an unexplained rise | Auto hue 288 on the sample gave 4 kills: the 3 real + one at 11.8s | **not reproduced** on the full-quality match: at hue 285 the reader made 0 false kills in 21. The phantom came from a 720p phone recording of the stream. Left alone until footage shows it again |
| T4 | **Fail loudly instead of `No kills found`.** A long scan with 0 own emblems means the HUD was not read; say so and point at calibration. Put hue + its evidence, flash count, own-emblem count and sample count in the diagnostic; route `_pipe_view` / `strip_samples` ffmpeg calls through `diag` (about 90 are invisible today). Remove "Set the colour by hand on the Clips page" — no such control exists. Fix the Tesseract hint that says `winget install --id Gyan.FFmpeg` | The diagnostic file alone could not answer this; the log could | **done 2026-10-08** — `HudUnread` with what to do; scanner numbers in the diagnostic; the scan's ffmpeg calls reported; Tesseract no longer gets the ffmpeg hint; a colour is saved only after a scan reads kills in it, and forgotten if one cannot |
| T5 | **"Pick your kill" fallback.** When measurement is weak, show 6–8 auto-found saturation-jump candidates in the bottom-centre and let the user tap one; take hue from the beam, card position from where it rises, own emblem from the frame before. The scan must then find that kill, or it reports the HUD unread | Prototype: a mark at 38.5s → hue 288, beam centred x=958 vs box 968. A **time-only** mark at 10s latched onto orange scenery (hue 32) — so the user must pick *where*, not only *when* | **not needed for now** — with T2 the measured colour is right on every alignment tried. Revisit if a HUD turns up that measurement cannot read |

Workaround already given to him: quit AutoStream, add `  hud_hue: 300.0`
under `cs2.exe` in `%LOCALAPPDATA%\AutoStream\config\clip_profiles.yaml`,
re-run. Passing the card-area check rewrites the profile and drops it (T1).

The sample recording, the three ground-truth kill times and the per-frame
readings belong in the regression corpus for T2–T3.

### Valorant: a team-mate's kills counted as yours (2026-10-08)

The same outside user's 50-minute Valorant stream (TDM, then a full match),
v1.42.0: the feed read 36 kills, the clips claimed 60. Reproduced on the
stream itself: 59 kill emblems, 46 added, **0 set aside as spectating**.
Ground truth by eye: 37 of the 59 were his. 13 were team-mates' kills he
watched while dead, 5 agent-select countdown rings, 4 TDM deaths/respawns.

| # | Fix | Status |
|---|---|---|
| V1 | **Spectating unseen behind a facecam.** `spectating()` read only the card bottom-left -- under his facecam every time. Added `dead()`: the combat report a dead player is shown, right of centre, read **before and after** the emblem (after alone threw away a developer kill-then-death trade) | **done 2026-10-08** -- 13/13 caught; developer recording vs Riot record: 0 of 19 own kills lost |
| V2 | **Agent select's countdown ring read as an emblem.** `menu()`: the red LOCK IN button under it | **done 2026-10-08** -- 4 of 5; the 5th is after lock-in, button gone |
| V3 | TDM: emblems while dead/respawning (3 left) | not started |

### Next — the Timeline effects picker (asked 2026-10-08)

**Straight after T1–T5.** On the Timeline page, the section that lists the
intros, outros and kill effects is poor UX and UI. Redesign it so that
clicking to change any effect opens a **dialog on the page** (not a window
of its own) with:

- **Recently used** effects first
- **Search** by name and by code
- A **preview** of each effect before it is chosen

| # | Item | Status |
|---|---|---|
| U1 | Timeline effects picker dialog: recent, search by name/code, preview | **done 2026-10-08**, v1.44.0 -- see Progress |
| U2 | **List the Valorant matches AutoStream has fetched, in the UI** (asked 2026-10-08). Riot match records are cached in `Videos\AutoStream\matches` (71 on the developer's machine) and decide whether a recording's kills come from Riot's record or from the screen -- yet nothing shows them. A list per match (map, mode, date, score, the player's K/D/A, which recording it lines up with), so a user can see a match was captured before cutting clips from it -- and see when one was not, which is why an outside user's run fell back to reading the screen | **done 2026-10-09**, v1.45.0 -- plus picking which of a video's matches to clip |
| U3 | **Lyric reels that copy real YouTube lyric edits** (asked 2026-10-09, after the samples page was liked): study real lyric edits of the same kind frame by frame -- font, size, placement, how each word arrives and leaves, colour, timing against the vocal -- and match them, measured the way the beat study measured cuts. **The user picks the typeface** (asked 2026-10-10): a Typeface setting beside the look, each look defaulting to its own face (Stamp Anton, Glow Poppins ExtraBold, Serif Crimson Text, Caption Kanit Medium, Scrawl Patrick Hand), all bundled OFL fonts so nothing downloads; changing it swaps the font only, never the look's motion or colour | **done 2026-10-10**, v1.46.0 -- see Progress |
| U4 | **Beat finder: hi-hats between the kicks set the tempo** (from the beat-vs-edit study, 2026-10-09: 3 of 10 real edits' songs read at the wrong tempo, e.g. 100 as 135) | **fixed 2026-10-10**, v1.46.0 -- see Progress. The study's other proposals (trust the bass hits on disagreement, a 0.30 s run-up) were measured or left; see the row |
| U5 | **See every reel in the Studio, not only the latest** (asked 2026-10-10): the library listed the newest ten of the user's 82 reels and nothing else | **done 2026-10-10**, v1.47.0 -- see Progress |
| U6 | **Put the lyrics anywhere** (asked 2026-10-10) | **done 2026-10-10**, v1.48.0; the stand-in only while placing, v1.49.0 -- see Progress |
| U7 | **Longer reels in any style; Keep every kill; Best order** (asked 2026-10-11, `dwayIR`) | **done 2026-10-11**, v1.52.0 -- see Progress |
| U8 | **Turning a setting on and off counted as two changes** (asked 2026-10-11) | **done 2026-10-11**, v1.52.0 -- see Progress |
| U9 | **See an edit without waiting for a render** (asked 2026-10-11): instant preview, and the render starts by itself | **done 2026-10-11**, v1.52.0 -- see Progress |
| U10 | **"Perfect fit (slower)"**: every kill on a hit, no 3-4 kill clip short a kill (asked 2026-10-11) | **done 2026-10-11**, v1.52.0 -- see Progress |
| U11 | **The play controls vanished during the preview** (asked 2026-10-11) | **done 2026-10-11**, v1.53.0 -- see Progress |
| U12 | **A new lyric style is not shown until a render** (asked 2026-10-11) | **done 2026-10-11**, v1.53.0 -- see Progress |
| U13 | **9:16 + Fit the whole picture: blurred bands, not black** (asked 2026-10-11) | **done 2026-10-11**, v1.53.0; the render already blurred them, the preview did not -- see Progress |
| U14 | **The effect picker: the preview big and in the middle** (asked 2026-10-11) | **done 2026-10-11**, v1.53.0 -- see Progress |
| U15 | **The Studio opens on folders, not on every clip** (asked 2026-10-11): folders first, a folder opens on its runs, a run opens on its matches, and the clips sit under the match they came from | **done 2026-10-11**, v1.54.0 -- see Progress, and the design under [UI work](#the-studio-opens-on-folders-not-on-339-clips-asked-2026-10-11) |
| U16 | **One registry behind every action, then Ctrl+K and a key sheet** (asked 2026-10-11): the Studio declares 147 `data-act` names and eight timeline keys and can enumerate neither, which is why it has no palette, no key sheet and no rebinding | **done 2026-10-12**, v1.58.0 -- 162 commands over 147 actions, Ctrl+K, `?`, `/api/studio/commands`, four offline rules. The old keydown block is still the one that runs the keys; see Progress |
| U17 | **Redo, and an undo you can step back through** (asked 2026-10-11): `studio.undo` is a pop stack behind one key, so a Ctrl+Z pressed once too often cannot be taken back | **done 2026-10-12**, v1.60.0 -- Ctrl+Z and Ctrl+Shift+Z, both buttons naming the step they cross, and a history that keeps the steps you undid -- see Progress. **No browser test yet** (scenarios 6.42-6.44) |
| U18 | **The timeline's missing hand: ripple, roll, razor and rate, more than one shot selected, markers and J/K/L** (asked 2026-10-11): `grep razor` and `grep ripple` return nothing in the package, and `sel` is a single index | **part done 2026-10-12**, v1.61.0 -- Roll, Razor, Escape-to-Select, J/K/L, in/out and marks. **Ripple was not built, deliberately: a trim already ripples here.** Rate and more-than-one-shot-selected are still to do -- see Progress |
| U19 | **Keyframes on six properties, never on speed** (asked 2026-10-11): every effect is a per-shot constant today; scale, position X and Y, rotation, volume and grade strength get a value lane, and speed stays a named ramp because the beat arithmetic inverts it | **UNBLOCKED 2026-10-13 -- the gate number exists.** On a 20-shot reel: the join alone is **13.0 s**, one re-cut shot adds **~2 s**, and a change that re-cuts all twenty costs **37 s**. So keyframes are affordable per shot and expensive wholesale, which argues for a lane only on shots that have one. Not started; the number to beat is the 13.0 s floor -- see Progress |
| U20 | **Write the reel out as a timeline another editor can open** (asked 2026-10-11): `<name>.reel.json` is already a project file; OpenTimelineIO and FCP7 XML make it one Resolve and Premiere can read, with a sheet saying what survives the trip | **done 2026-10-13**, v1.64.0 -- `clips/interchange.py`, both formats, and the sheet written beside the file -- see Progress |
| U21 | **The effect picker closed on every choice** (asked 2026-10-11): "to add 4 effects I have to open the page 4 times" -- a single choice applied and shut the dialog, so trying two endings against each other meant opening it twice | **done 2026-10-11**, v1.54.0 -- it applies as you click and **Done** closes it; see Progress |
| U22 | **"Where is the option about the order of the clips?"** (asked 2026-10-11): Best order shipped in v1.52.0 and lived in the drawers strip at the foot of the Clips tab, while the Make dialog asked the same question its own way (As chosen / Most kills first / Oldest first) and could not reach it | **done 2026-10-12**, v1.55.0 -- one Order control, in the dialog, all six arrangements -- see Progress |
| U23 | **The example on each effect card is messy and soft** (asked 2026-10-11) | **done 2026-10-12**, v1.55.0 -- cut from clips you starred, at 640px/CRF 26 -- see Progress |
| U24 | **"I don't know from which folder, from which run the current clips are selected"** (asked 2026-10-11), and the Clips tab squeezes three pages into one | **done 2026-10-12**, v1.55.0 -- a count at every level, a band naming the runs, and Clips / Reels / Looks as three tabs -- see Progress. The mockup the design was agreed from: <https://claude.ai/artifact/UNV7aNTwJBunmJFQkHWpEw> |
| U25 | **Pick how the lyrics are displayed, not just the look** (asked 2026-10-12): "right now the default is one word at a time ... like one whole line at a time, like a typewriter" | **done 2026-10-12**, v1.56.0 -- five reveals beside the look and the typeface -- see Progress |
| U26 | **"I made some changes in the reel but the rendering does not start for the unapplied changes"** (asked 2026-10-12) | **done 2026-10-12**, v1.56.0 -- it was starting, and being thrown away by the next edit while showing 0% -- see Progress |
| U27 | **The lyrics need a box, a size and an opacity** (asked 2026-10-12): "it takes the whole screen space ... there is also no option to select opacity" | **done 2026-10-12**, v1.57.0 -- Width, Size and Opacity beside the look -- see Progress |
| U28 | **Draw the lyric boxes on the picture, and deal the lines round them** (asked 2026-10-12): "instead of giving the user the size and width option as main option ask them to make a BOX on the screen ... the first line appears on the first box then the second line appears on the second box ... the 4th lyrics again on first" | **done 2026-10-12**, v1.59.0 -- up to six boxes, drawn, moved, resized and turned on the preview; the lines deal round them in the order drawn -- see Progress. **No browser test yet** (scenarios 6.38-6.41) |

Follow the UI contract below (tokens, focus rings, one JS scope) and ship it
with a browser test — UI #10, the shared player component, pairs naturally
with the previews.

### A new style, "Fast-paced headshot" (asked 2026-10-13) — specified, not started

Headshots only, hard monochrome, flipping to photographic negative on the beat.
Reverse-engineered from an anime edit the user supplied, then cut by hand with
ffmpeg outside the app and measured until it matched. The reference build is
`clips\reels\MONO-ALL-HEADSHOTS-Murder-nearfit.mp4`.

**The full spec is [STYLE-FAST-PACED-HEADSHOT.md](STYLE-FAST-PACED-HEADSHOT.md)** —
every number in it is measured off that reel, with the acceptance ranges, the
verification checks and the nine pitfalls that cost real time. Read it before
touching this; do not re-derive the numbers.

The one genuinely new thing it needs is a **reel-level beat pass**: its effects key
off the song's beat grid, not off each kill, which the parts bin cannot express
today (`k12`/`k06` key off `kt`). Everything else is a new grade row, a style
entry, and three framing options.

Blocked on one thing before it can run unattended: picking which kills are worth
cutting is still a human looking at contact sheets (§4.2, §15).

### Phase A — Tier 1, the market unlocks

These change **who can use the product**, not what it does. Nothing in Phase B
matters until these are in.

| # | Feature | Why it is first | Status |
|---|---|---|---|
| A2 | **Clips-only install path** | Removes the Google account from first run — the hardest step, for a feature most clipper users never want | **done** — and the wizard is now shaped by the platform, so Twitch and Kick skip the four YouTube-only steps |
| A3 | **Instant-replay hotkey** | The most-used feature in every competitor. Cheap, and it covers every game at once | **done** — OBS replay buffer, a global hotkey, a dashboard card that says whether OBS is actually holding one |
| A4 | **Generic highlight detection** | Audio energy, kill-sound onset, input burst, scoreboard delta. Turns "4 games" into "any game" | **done** — audio energy against a rolling baseline, as a profile mode any game can use |

**A1 is worth more than the rest combined, and is not the hard build it
sounds like.** Neither Twitch nor Kick exposes an API that starts a broadcast,
because neither needs one: the stream is live the moment OBS pushes RTMP to a
persistent key. So none of the YouTube broadcast lifecycle applies — no
`liveBroadcasts` dance, no 10,000-unit quota, no OAuth verification regime, no
24-hour channel activation. Three things: set the key in OBS, start the
output, set title and category over Helix or Kick's API. The hardest platform
was built first.

**Credentials are in place** (2026-10-04), in `secrets/twitch.json` and
`secrets/kick.json` — both gitignored. Two facts recorded there that shape the
build:

- **The redirect URI must be fixed and pre-registered.** YouTube's flow uses
  `run_local_server(port=0)`, a different port every time, which Google allows
  for installed apps. Twitch and Kick do not: both are registered against
  `http://localhost:8787/oauth/<platform>`, which is the dashboard's own port,
  so the callback is served by the server that is already running.
- **Kick is OAuth 2.1 with PKCE and 2-hour tokens.** Refresh handling is not
  optional there, where Twitch's ~60-day tokens would let you be lazy.

**The OBS half already exists.** `obs.configure_stream()` already speaks
`rtmp_custom` with an arbitrary server and key, which is exactly and entirely
what Twitch and Kick need. The real work in A1 is not the platform APIs — it
is that `engine.py` is hard-wired to YouTube (`self.yt`, `cfg.youtube.*`,
`from .youtube import YouTube`) and has no platform seam. CLAUDE.md calls that
file "the only place a broadcast starts, retitles or stops", so the seam wants
building as its own change, with YouTube as the only implementation and no
behaviour change, before any second platform is added on top.

### Phase B — the first six onboarding changes

Run these alongside Phase A. They decide whether a stranger keeps the app
past the first session, and four of them are setup failures rather than
missing features.

| # | Change | Status |
|---|---|---|
| B1 | Clips-only is the **default** first run; go-live becomes opt-in | **done** — offered first and marked Recommended |
| B3 | Configure the OBS websocket automatically — read OBS's own config, enable, set port and password | **done** — reads it as before, and now writes it too (only while OBS is shut, because OBS rewrites the file from memory when it quits) |
| B4 | Refuse to finish setup while the OAuth consent screen is in Testing (it expires in ~7 days and looks like the product breaking) | **done, differently** — publishing status is not exposed to the client, so refusing is impossible. Inferred instead: a token still refreshing at day 9 proves the app is published; before that, days 5–7 get a warning |
| B5 | Preflight YouTube live enablement before anything else (a new channel takes 24h; finding out at go-live wastes an evening) | **done** — one quota unit, right after sign-in |
| B6 | Finish setup into a *running* engine (today nothing streams until a manual restart, and no screen says so) | **already done** — `await_setup()` starts the engine in-process. The roadmap entry was stale |

### Phase C — Tier 2, close the visible gaps

| # | Feature | Status |
|---|---|---|
| C2 | Match summaries for CS2 and Valorant — both already have exact ground truth | **Counter-Strike done**; Valorant still to come. The cut rides `master_segments`, already proven by the Rivals summary. **The switch did nothing until v1.54.0**: the page sent `match_summary` and `webui.clips_run` never copied it into the job's options, so no run ever made one -- fixed, with a test on both ends |
| C4 | Vertical live output | not started |
| C5 | Auto title, description, chapters and thumbnail from the match result | **chapters done** — exact offsets for the montage. Chapters in the live VOD's description are **deliberately not built**; see Progress |
| C6 | Clip ranking — a ranked shortlist of 5 beats a folder of 40 in filename order | **done** — density breaks the tie on kill count, and the best five are marked |

### Phase D — the remaining shipped-behaviour fixes

Fourteen more, from the 2026-09-25 test report. Grouped by area, roughly in
this order: **Quota** (3), **Reliability** (3), **Correctness** (4),
**Detection** (2), **Security** (1), **Measurement** (1). Several are in
`AutoStream-test-report-2026-09-25.md` by item number.

### Phase E — Tier 3, deepen the moat

Live VOD chapters · weekly recap reel · community game profiles · multistream ·
duo/team POV cutting · mobile review app.

### Phase F — parked, last (reprioritised 2026-10-08)

Moved here by the user on 2026-10-08, below Phase E, so the CS2 card tally
and the rest of the order come first. Nothing is lost: each row keeps the
status it had when it was parked. Do not pick these up ahead of Phase E
without the user saying so.

| # | Feature | Was | Status |
|---|---|---|---|
| A1 | **Twitch + Kick auto go-live** | Phase A | **code done** — seam, both platforms, sign-in, UI and the two paired UI items. Twitch verified against the live API; Kick needs `channel:read` re-granted. No real stream pushed yet |
| B2 | Code-sign the binary (SmartScreen sits between every download and every install) | Phase B | **blocked** — needs a purchased certificate (OV ~$200/yr, or an EV token). Nothing to build until one exists |
| C1 | Auto-publish with scheduling (TikTok, Reels, Shorts) | Phase C | not started |
| C3 | Four to six more titles, each shipping with its regression harness | Phase C | not started |

### Deliberately not on the roadmap

- **AI co-host avatar** — Streamlabs, ai_licia and Questie are ahead and
  better funded.
- **Cloud rendering** — contradicts the local-first promise, which is the
  product's main defence.
- **macOS** — no game capture story, and all four supported titles are
  Windows-first.

Do not add these back without a reason that is written down here.

---

## State of the tree, 2026-10-12

- `__version__` is **1.58.0**, unreleased, on branch `studio-u16`.
- **v1.57.0 is published and on `main` as `c166dcc`**
  (<https://github.com/hardikneeravsharma/AutoStream/releases/tag/v1.57.0>).
  It carries v1.56.0 as well, which was on `main` as `62106ff` but never
  released -- its build was killed mid-flight rather than freeze uncommitted
  work into artifacts labelled 1.56.0.
- **One PR will be open**: `studio-u16`, off `c166dcc`. It carries U16 (the
  command registry, Ctrl+K and the key sheet), the blur-gate that takes ~60%
  off a render with the i05 opener, and a join that reports its own progress.
- **THREE SESSIONS SHARE THIS WORKING TREE.** `C:\autostream` is worked by
  more than one agent at a time and `C:\autostream-tempo` is a second
  worktree holding `main`. Stage explicit paths, never `git add -A`; say so
  before switching branches or stashing; and remember a build freezes
  whatever is in the tree, including somebody else's uncommitted work.
- **THE BROWSER TIER HAS NOT RUN IN FULL SINCE v1.54.0**, at the user's
  instruction to skip unnecessary tests. Tier 7 against the built exe has not
  run since v1.53.0: it needs the app closed, and it has been in use. U16 adds
  four controls and two keys to a page, and scenarios 6.34-6.37 are written
  but have no test yet -- **run the browser tier before the release after
  this one**, or those four controls are shipping on unit tests alone.
- The sweep's `REACHED_FLOOR` is still **132**; the Studio now declares
  **151** controls rather than 147 (the command list and the key sheet), and
  the whole surface **230** rather than 226.
- Releases are built with `scripts\build.ps1 -Dist -HandOff` with the app
  left open; it closes the app only when idle (about two minutes) and
  reopens it. **Do not run it while the user is editing a reel** -- HandOff
  asks the app to quit the moment it goes idle, and a session was lost to
  exactly that.

### What is not finished

Written down rather than left looking done:

- **Valorant match summary** (one video per match, the real round score,
  Ace/Clutch chapter names) is planned and **waiting for the user's go-ahead**.
  Today the match summary is Counter-Strike only (see C2 below).
- **The friend's AMD machine** has not confirmed v1.50.0's GPU path; the
  diagnostic should show `d3d11va` decode and `h264_amf` encode.
- **CS2 close kills** need measuring against demos before anything is built;
  Valorant's were measured and the screen reader already separates them.
- **V3** (Valorant TDM: emblems while dead or respawning) is not started.
- **MONTERO (179 BPM)** still reads at the wrong tempo (134), and the
  study's **0.30 s run-up** needs its own measurement against the Studio's
  per-style run-ups -- both from the U4 row.
- **What the instant preview leaves out**: the colour grade, the kill
  effects and Stamp's grey are in the render only; the label on the preview
  says so. The picker's sharp copies need two clips longer than 4 s with a
  kill, and are not made while live, recording, cutting clips or rendering.

- **A1 has never gone live.** The seam, both platforms, the OAuth sign-in and
  the UI that follows the choice are in and tested against the live APIs --
  Twitch resolves its channel id and categories. But no stream has been
  pushed to either, and Kick's sign-in came back with three of its four
  scopes, so `channel:read` has to be granted before a Kick session can
  start. That one needs the user at the keyboard.
- **C2 is Counter-Strike only**, and until v1.54.0 it was nothing at all:
  the Clips page's "Also make the whole match as one video" sent a flag the
  server dropped. The flag now reaches the job. **Valorant still has no
  match video**, and the gap is bigger than wiring: `valorant_match.rounds_from`
  gives the ceremonies (ACE, CLUTCH) and who won each round, but leaves
  `score_before`/`score_after` at `(0, 0)` -- so every chapter would read
  `0-0` -- and it derives a round's bounds from its first and last kill, so a
  round nobody died in is dropped. The switch is also hidden for Valorant,
  whose profile deliberately leaves `rounds` False. Those three, then the
  video.
- **C5 is the montage's chapters only.** Chapters in the live VOD's
  description need recording-offset to VOD-offset arithmetic that cannot be
  verified without a real stream; see the Progress row.
- **B2** needs a purchased certificate. Blocked, not pending.
- **C1, C3, C4** need credentials or real footage that is not on this
  machine.

## UI work, carried alongside

From **AutoStream UI review — handoff for feature work** (2026-10-04):
`https://claude.ai/code/artifact/4beefc06-b3d9-4576-821b-354bfea246a3`

**Not a phase of its own.** Fifteen fixes shipped together would be a release
nobody can review and a month with no features in it. They are paired to the
feature that already has that file open, which is what the review itself
recommends: *"if your feature work already has that file open, take the
adjacent fix with it."*

The rule: **every feature ships with the UI items for the files it touched.**
If a feature touches a file with no paired item, it ships none. If it touches
`css.py`, it takes the contrast fixes.

| With | UI items | Why these |
|---|---|---|
| **A1** Twitch + Kick | **#6** Settings nav below 900px · **#8** Settings search across ~90 keys | A1 adds the platform picker to `settings.py`; the nav is already clipped mid-word there with no affordance, and A1 makes the page longer |
| **A2+B1** clips-only install | **#13** Setup step 2 as a checklist · **ARIA on `setup.py`** | A2 rewrites the first run. `ui/setup.py` has **zero** ARIA attributes today — studio has 83, clips 70 — and it is the first screen a new user meets |
| **A3** instant-replay hotkey | **#1** `--text-on-accent` on accent fills · **#7** Dashboard metric strip | Both are `css.py`, 45 minutes together, and the hotkey needs a dashboard readout anyway |
| **A4** generic highlights | **#3** the Clips stepper tick | Both in `clips.py`. See below — this one is ours |
| **C1** auto-publish | **#2** `--on-media` token pair | Publishing shows badges over video frames, which is the exact thing defect 2 breaks |
| **C4** vertical live output | **#10** shared player component | A second encode wants one player, not a third `<video>` |
| **C6** clip ranking | **#12** build summary replacing the combinatorial counter | Both are about what the Studio says is worth making |
| **Any new pane** | **#2**, **#10**, **#14** | The review names these three as the ones whose absence costs rework later |

### Studio import, asked for 2026-10-04

Two gaps in "Add your own clip", both confirmed in the source rather than
guessed. Small, and they pair with each other -- the same dialog, the same
afternoon.

**S1 · Adding clips, plural.** ✅ **done 2026-10-05.** `studio_impAdd` takes one file and stops:
`/api/clips/pick` returns a single `path`, because `clips_pick` calls Tk's
`askopenfilename`. Somebody with a folder of twenty clips does the whole dance
twenty times. The change is `askopenfilenames` behind a `multi` flag, a
response that carries `paths`, and a loop in `studio_impAdd` -- then the
marker opens on the first and moves to the next on Save, so a batch is one
pass rather than twenty.

Keep the single-file answer working: `clips_pick` serves intros, outros and
songs as well, and none of those wants a multi-select.

**S2 · The kill marker should reopen for any clip.** ✅ **done 2026-10-05.** It is gated on
`c.imported` ([studio.py:954](../autostream/ui/studio.py#L954)), and that flag
is set only for clips that came in through import
([clips/studio.py:276](../autostream/clips/studio.py#L276)). So a clip
AutoStream cut for itself has no way back into the marker at all: if the
detector put a kill half a second late, or a clip deserves a better title,
there is nothing to press.

The marker already works on any path -- `studio_impOpen(path)` does not care
where the clip came from. What is missing is the way in. Show Edit on every
clip, and let a detected clip's marks be corrected the same way an imported
one's are.

> There is a decision inside S2 worth making deliberately: a detected clip's
> kills come from the detector, so editing them means the run's own record and
> the clip's record can disagree. Either the edit writes back to the run, or
> the clip carries an override that wins. The second is smaller and does not
> rewrite history; the first keeps one source of truth. Pick one before
> building, not during.

**Where these ship:** with **C3** (four to six more titles) or **A4** (generic
highlight detection) -- both bring in clips the detector is less sure about,
which is exactly when being able to correct a mark starts to matter. If
neither is close, S1 stands alone at about half a day.

### The Studio opens on folders, not on 339 clips (asked 2026-10-11)

**U15. ✅ done 2026-10-11, v1.54.0** -- built as designed below; the Progress
row has what the three risks turned out to be.

**U15.** The Studio's library is one scroll. `studio_renderLib` writes a `<h3>`
per game and a `<section>` per run folder, and inside every one of them a tile
per clip -- so the page the player lands on is the whole library at once.
Measured on the developer's own machine today, through `clips.studio.library()`:
**339 clips in 42 run folders across 4 games**, plus 90 reels above them. That
is 339 lazily-loaded thumbnails and 4 buttons per clip in a single pane, and
finding "the Haven match from Saturday" means scrolling past everything else.

The ask is a drill-down, three levels, each one a thing the library already
knows:

1. **Folders.** One card per game (VALORANT 222 · 13 runs, Counter-Strike 2
   53 · 7, Delta Force 44 · 2, Other 20 · 20), a four-still mosaic on each,
   plus the ★ Favourites card, which cuts across games as the chip does now.
   Five cards instead of 339 tiles.
2. **Runs.** A folder opens on its runs, newest first -- the date label
   `_folder_label()` already makes, the clip and kill counts, and **a chip per
   match in that run**.
3. **Clips.** A run opens on the clips it holds, **grouped under the match
   each was cut from**: map, mode, score, the player's K/D/A, where the match
   starts in the recording, and a `Select match` beside the existing
   `Select run`.

**Nothing in level 3 needs new detection.** Both halves are already on disk and
were checked against each other rather than assumed: a run's `session.json`
carries `demo.matches`, each with the match id and its `offset` into the
recording, and the Riot record the Clips page fetched for U2 gives the map, the
mode and the score through `valorant_match.summary()`. Assigning each clip to
the match whose span contains its `start` on the 10 Oct 22:15 run gives
**10 + 4 + 15 + 9 = 38 clips** -- the whole run, nothing stranded -- and the
kills per group are **18 / 23 / 24 / 27**, exactly what Riot's record says the
player got in Lotus, Drift, Haven and Piazza. A run with no match records (CS2,
Delta Force, imports) simply shows one group, and CS2's rounds are already on
each clip (`round` in `clips.json`) when that is worth a second grouping.

A clickable mockup of all three levels, built from the real library, is in
[docs/mockups/studio-folders.html](mockups/studio-folders.html).

Three things to settle before building, because they are what the change can
break:

- **The sweep reaches controls by walking the rendered page.** Clip tiles
  behind two clicks are not rendered, so `REACHED_FLOOR` (117 of 190) drops
  unless the browser tier learns to open a folder and a run. Raise the tier
  with the feature, in the same PR, or the floor fails for a page that is
  working.
- **Where the view lives.** `studio_renderLib` rebuilds the whole pane on every
  change, and the selection tray survives that today only because it is rebuilt
  from `studio.selected`. The open folder and open run have to be state of the
  same kind, or coming back from making a reel drops the player at the top.
- **Search has to keep reaching every clip**, from level 1, or the drill-down
  has taken something away. The box filters folders and clips both.

Two adjacent defects the mockup made visible, both small and neither invented
for this entry:

- **20 of the 42 folders are single imported clips in "Other"** -- all of them
  Valorant. An import writes no `game`, so `library()` falls back to `Other`,
  and the same ten source clips are there twice from two import runs. The game
  is in the file name the importer already parses.
- **A map key the table does not have shows Riot's internal name.** `Plummet`
  is not in `MAP_NAMES`, so that run's chip reads `Plummet` rather than the
  name on the loading screen. One line, and the fallback is working as
  designed -- it is the table that is behind.

**Where it ships:** on its own. It touches `ui/studio.py` and nothing else in
the detector, and it pairs with **#10** (the shared player component) only if
the clip tiles get a player at the same time.

### The timeline grows a hand (asked 2026-10-11)

**U16-U20.** Asked after reading the [`storytold`](https://github.com/storytold)
organisation -- ArtCraft: 56 Apache-2.0 clean-room rewrites of Adobe's tools in
Rust, `filmcraft` for Premiere and `effectcraft` for After Effects -- and asking
what of it AutoStream should take. The plan, the mockups and the sources are at
`https://claude.ai/artifact/SgB4dwSSGY5yBMDSjJWC6x`.

**None of their code comes across, and none of it needs to.** They are egui on
wgpu with their own H.264 and ProRes decoders; we are Python, ffmpeg filter
graphs and HTML the daemon serves, and the browser tier is the only thing that
has ever caught a real UI bug here. What is worth taking is their
*specifications*: one command registry behind every action, a Premiere key table
with the conflicts already reconciled, a measured hit-test rule, and
OpenTimelineIO. Both sides are Apache-2.0, so a copied table needs a NOTICE line
naming the file it came from; their brand licence is separate and forbids the
names, so no "ArtCraft" or "FilmCraft" wording in our UI -- only the format
names.

**The decision that frames all five: one interface, layered -- not a Basic and
an Advanced Studio.** The question was put as a choice between two UIs the user
switches between and one UI with the advanced parts folded into it, and the
second is right here for reasons this repo can point at:

- **U15 is the precedent, and it shipped the same day this was asked.** The
  library did not grow a simple copy and an advanced copy -- it grew *levels*,
  and the search still answers from every one of them (`studio_visible`), so
  nothing sits behind a level you did not know to open. A skill switch would be
  a second axis on top of four panes and three library levels.
- **Folding is already this page's mechanism, twice.** `studio_grp()` renders
  every inspector group as a `<details>` and remembers it in `studio.grpOpen`;
  U15's open folder and run live in `studio.game`/`studio.run` for the same
  reason. Layering extends something that exists; a mode invents one.
- **The trade-off is not features against simplicity, it is default state
  against reachable state.** A folded control costs a beginner nothing and an
  expert one click. A control in the other mode costs the expert a switch and
  costs the beginner the knowledge that it exists.
- **The cost U15 already paid applies to every folded lane.** The sweep reaches
  controls by walking the rendered page, so a lane that opens folded is not a
  reachable control. U15 answered that with two new sweep states rather than a
  lower floor; `REACHED_FLOOR` is **132 of the 226 controls the source
  declares** (147 of them on the Studio), and each item below raises it in its
  own PR.
- **Where a mode *is* right, the repo already has it:** `ui.developer_mode`,
  which hides the 1.19-1.46x real-time Counter-Strike reader. Gate by cost,
  never by skill. Slow, destructive or silently-wrong goes behind that flag;
  merely advanced gets folded.

**U16 · Name every action.** `{id, label, scope, keys, enabled(state),
run(state)}`, one registry, with `/api/studio/commands` so the browser tier can
enumerate and run them. Today the vocabulary is 147 distinct `data-act` strings
and eight bindings in one `keydown` block, and nothing can list what the editor
can do -- which is exactly why there is no palette, no key sheet and no
rebinding. Then Ctrl+K (showing each command's key, and *why* a command is
unavailable rather than greying out in silence) and a key sheet on `?` generated
from the registry so it cannot drift. Port their two offline test rules with it:
**no key bound twice in one scope**, and **no binding naming a command that does
not exist**. Everything after this is cheaper, which is why it is first.

> **The keydown scope order is load-bearing.** It is importer, then the effect
> picker, then Escape, then inputs, then the song pane's `K`, then "a focused
> button owns Space, Backspace and Enter". Lose the order and Space on a focused
> button starts playback instead of pressing it. The registry carries an
> explicit scope with the same precedence, and the old handler is not deleted
> until a test replays every existing key in each pane state.

**U17 · Redo, and a history.** `studio_undo()` pops the stack; there is no
redo and `studio.undo` is emptied on load. Keep the stack as a cursor rather
than a pop and pair each command with its inverse. **One correction to the plan
as written:** it proposed building the history list out of labels that
`studio_change(fn, label)` "writes and throws away" -- that stopped being true
in v1.52.0. The labels feed `studio_touched()` and the change list the sync
strip shows. So a history panel reads the same data rather than inventing it,
and must never become a second list that says something different.

**U18 · The six tools and a real selection.** Ripple, roll, razor and rate
stretch on top of today's move and trim, each also reachable as a modifier on
the drag people already know (Alt ripples, Ctrl rolls, Esc returns to Select)
so nobody picks a tool and nobody is stranded holding one. Then in and out
points, markers, J/K/L and frame-stepping -- the import marker already steps
frames, so that behaviour is lifted, not written. Copy their hit-test rule
verbatim: an edge is the 7px nearest the cut, a third of a narrow clip, and from
the cut rightwards it belongs to the right clip's In. That detail takes a week
to get right by feel and they have measured it.

Four things this must not take away, all read out of the source rather than
remembered:

- **Slip already exists** -- `data-act="studio-slip"` gives +/-0.1 s and +/-1
  frame, the only frame-accurate and keyboard-reachable route to a kill mark.
  A drag is an addition; the buttons stay.
- **`sel` stays the anchor index.** It feeds the inspector, the frame handle,
  move left/right and delete; a set goes *beside* it and is consulted only when
  it holds more than one. Note that the Studio already has a real
  multi-selection -- `studio.selected`, with Select run and Select match from
  U15 -- and it selects *clips in the library*, not shots on the timeline.
  Two selections that look alike and mean different things is the trap here.
- **Delete refuses to go below one shot.** A ripple-delete written fresh drops
  that guard and empties the reel; it moves into the command's `enabled()`,
  which the palette and the key both read.
- **The server keeps the arithmetic.** Ripple, roll and rate each post to
  `/api/studio/check`, which clamps and returns every derived time, exactly as
  drags do now. Two implementations of where a kill lands would disagree
  eventually.

**U19 · Keyframes, and the one property that cannot have them.** `grep -i
keyframe` across `autostream/` returns CSS animations and ffmpeg seek points and
nothing else: every effect is a per-shot constant. A value lane -- diamonds,
linear/ease/hold, a velocity curve -- for scale, position X and Y, rotation,
volume and grade strength. **Speed is deliberately not one of them:** `pieces()`,
`_stretch_of()` and `output_at()` compute where a kill lands from the *named*
ramp, and `stretch` already slows a run-up so the kill reaches its mark;
keyframing speed means inverting an arbitrary time warp to keep kills on their
beats. The page is the easy half -- the risk is that where ffmpeg takes no
expression the shot must be segmented, and segmenting is what breaks the
per-shot cache an edit answers from. **The gate is a measurement, not a
review:** render time per edit on a 20-shot reel. We have no such number today;
take it before starting, and if the lane makes it worse the lane ships
read-only.

**U20 · Interchange out.** `<name>.reel.json` already holds every shot, where
its kill lands, its speed, its effects, the transition into it, the grade, the
song and the offset into it -- that is a timeline, so it converts. Write OTIO
and FCP7 XML, with an export sheet that states plainly what survives (cuts,
order, lengths, source timecodes, speed ramps, kill marks and the beat grid as
markers, the song as an audio track) and what is baked or named-only (our
transitions and effects, lyrics, titles, facecam layout). A silent downgrade is
how somebody loses an afternoon. Reading OTIO back comes later and only for
cuts. Cheap, offline-testable, and it changes what AutoStream is -- a step in a
pipeline rather than a box that emits an mp4.

**What was dropped from the plan, and why:**

- **Ctrl+K as a way to find *clips*.** U15's search already answers across the
  whole library from any level. The palette is for commands; a second search
  over the same clips would be two answers to one question.
- **"Open the rendered reel on the timeline, so nothing is a dead end."**
  Shipped in U5 -- `studio_reelCard` has Open timeline on every reel that has a
  project, and says so plainly on the ones made before the Studio.
- **"3 changes since you watched it."** Shipped in U8 and U9.
- **"Render the in/out range only."** ⛔ Now a bad idea. U9 made the render
  start by itself after an edit and U8 made the change list honest about what
  has not reached the video; a part-render makes that strip claim the video
  matches the timeline when it matches a slice of it. In/out stays a *play*
  range and a navigation aid. If a range render is ever wanted it is an explicit
  button that leaves the rest listed as pending.
- **A Basic/Advanced mode.** See the decision above.
- **`craft-fonts` for reel titles.** U3 already bundles five OFL faces with a
  per-look typeface picker; a second licence-clean font set answers a question
  nobody has.
- **Embedding their WASM build, panel docking, plugin hosting, `.prproj` /
  `.aep` import, our own codecs, a second UI toolkit.** All out, as the plan
  itself concluded. AutoStream's premise is that the clips find themselves and
  the reel builds itself; the timeline exists to fix the tenth the automation
  got wrong, not to be where anyone starts.

**Out of scope for all five, in writing:** the whole Clips pane (parts bin,
examples, vary, restyle, favourites, the import marker, intros), the Song
shaper, the Facecam linker, and the U15 library. Nothing above touches them,
which is exactly how a page gets quietly re-laid-out during someone else's
refactor. The sweep's reachable-control floor is the detector if it happens
anyway.

**Where these ship:** U16 first and on its own, because the rest are cheaper
once actions have names; U17 with it or just after. U18 is the large one and
wants a release to itself. U19 does not start until its render-time number
exists. U20 is independent of all four and can go whenever there is an
afternoon. Each lands on `main`, in a release and in the local `dist\AutoStream`
build before the next starts, every new control enters
[docs/UI-SCENARIOS.md](UI-SCENARIOS.md) before its test, and each tool gets one
browser test against the built exe -- a razor wired to nothing passes every
offline test there is. One more number nobody has taken: **clips-ticked to
reel-rendered on the simple path.** Measure it before U16 and after each item;
if it grows, the item is wrong.

### Standalone, when nothing is adjacent

**#15** lazy-render the Studio panes. ⛔ **Not doing — the premise did not
hold.** The review counted 5,348 of 6,325 DOM nodes inside `#view-studio`.
Measured 2026-10-06 in a real browser on the v1.42.0 build, after the JS ran:
**1,614 elements in total, 579 (35.9%) in `view-studio`**; the served HTML has
2,408 with 497 there. Either an older build or a loaded project was measured.
579 hidden nodes are not worth the restructuring risk. Reopen only with a new
measurement that says otherwise.

**#14** the breakpoint scale. ✅ **done 2026-10-06** (`922288f`, on
`feat-ui-standalone`, not yet released). See Progress.

### One of these defects is ours

**Defect 3 — the Clips stepper marks a future step complete.** On step 2,
step 3 "Style" shows a tick while 4 and 5 are numbered. That is the stage rail
shipped in v1.40.0: `clip_steps()` sets each step's done flag from whether its
*card* has content, not from whether it is before the current one. A stage you
have not opened reads as finished.

It is paired with A4 above because both are `clips.py`, but it is a bug we
introduced and should not wait if A4 slips.

### The contract, which is binding

`autostream/theme.py` holds the token system and it measurably works — a
contrast pass found **zero failures on 10 of 12 page/theme combinations**. New
markup must not break it:

- **No literal colours outside `theme.py`.** No `#fff`, `#000` or `rgba()` in
  `css.py` or a page module.
- **Tokens name a role, not a hue.** `--accent`, not `--blue-500`.
- **The accent budget is four uses.** The rail marker and the settings nav
  marker are two of them.
- **Colour is never the only channel** — a status is never only a coloured dot.
- **Spacing on the 4px grid**, `--space-1 … --space-12`. No `padding: 13px`.
- **Focus rings on `:focus-visible` only**, never `:focus`.
- **One top-level JS scope, prefixed names.** A bare `const` in a page module
  takes the whole page down if it collides.

### Re-running the review

Every page rendered offline with real CSS and JS against a mocked API; the
daemon was never started. `webui.page("midnight")` and `webui.page("daylight")`
return the whole document with no server. Two traps the review records: the
Studio sub-tabs are `disabled` until a project exists, so enable them in JS
before clicking; and an `<option>` inside a closed `<select>` reports 1:1 and
is not a real failure.

The harness is not in the repo yet. It belongs under `tests/` or `scripts/`
next to the browser tiers, and would be a sensible thing to take with whichever
feature next touches `css.py`.

## Progress

One row per feature as it lands. Newest first. Fill in the date, what shipped,
and — the part that matters to the next session — **what it changed about the
plan**, because a roadmap that never moves was never being followed.

| Date | Item | What landed | What it changed |
|---|---|---|---|
| 2026-10-14 | **"Up to date" stops being said about a release that is newer**, v1.67.1 | v1.67.0 was tagged, written up and published **with no assets at all** — the build was never uploaded — so the updater asked GitHub, was told 1.67.0, found nothing to download, and printed *"You have the latest release. 1.67.0 was published on 13 October"* underneath the words *"up to date"*, beside a lower version number. `update_check` now answers `newer` separately from `available`, and `set_verStuck` gives the page its own sentence for it: the release exists, it is newer, it has no package attached, here is the page to look at. Reported as an updater bug; it was a release bug that the updater described wrongly. This release carries the assets v1.67.0 never got. | **`available` was two facts in one boolean.** "A newer version exists" and "there is something to download" had been identical for sixty-six releases, so folding them cost nothing until the day they came apart — and then the page asserted the opposite of what it had just been told. Any field that answers two questions will eventually answer one of them wrong; the fix is to let it answer one. **And `.sha256` sidecars stopped being uploaded at v1.64.3** — five releases where `build.ps1` wrote the checksums and the upload left them behind, so every download since has been unverified with only a line in the log to say so. Both are the same slip: the release step is by hand, and nothing checks the finished release against what the build produced. **And the build that shipped this could not run at first**: `obs64.exe` holds four VC runtime DLLs out of `dist\AutoStream\_internal`, because AutoStream launches OBS and OBS inherits the app's directory in its DLL search path. Closing AutoStream frees nothing, the clear deletes everything else before failing, and what is left is a gutted install that will not start. `build.ps1` now asks Restart Manager and prints `held by: obs64.exe (pid N)` instead of a list of suspects. |
| 2026-10-13 | **The beat engine**, v1.67.0 (STYLE-FAST-PACED-HEADSHOT work item 2) | `o09 Beat flip` and `o10 Beat flip (bars only)`: the picture snaps to photographic negative on the song's grid, with a brightness kick on every beat and two frames of black immediately before the drop. Measured against ffmpeg on a flat colour: **24 flips over 12 seconds at 120 BPM, one frame on a beat and three on a bar line** -- the specification's own shape. `studio.beat_engine()` builds it and `assemble_command` puts it in the post chain; `apply_song` now keeps the song's drop on the project, because finding it means decoding the song and that is a thing to do once. | **It needed no extra encode.** The spec recommends a separate pass over the joined body, which is reasonable advice from OUTSIDE the app -- there is no joined body to hang a filter on out there. Inside, `assemble_command`'s post chain already runs over exactly that, in absolute v-time, in a pass that was happening anyway. One encode, not two, and ~20 s a reel saved. **And the specification's windows land on a frame edge.** 0.0167 and 0.0500 are exactly one and three frames at 60 fps, which is the worst place for a threshold: measured against ffmpeg, 0.0167 caught TWO frames (1/60 is 0.0166667, which is under it) and 0.0500 caught four, because the phase offset is a large number and `mod` hands it back a few picoseconds light. 0.012 and 0.045 sit between frames, cost nothing, and cannot land on the edge. **Bar-only is a part, not an inference**: the spec ties it to letterboxed framing, but the two are otherwise independent and a control that changes itself is a control nobody trusts -- so `o10` is offered, with the photosensitivity reason written next to it. |
| 2026-10-13 | **"Fast-paced headshot", the first two pieces**, v1.66.0 | `g13 Hard monochrome` and a rigid beat grid in `beatsync`. **Every number was re-measured rather than copied**, and the spec's own harness was validated first: measured over the reference reel's gameplay panel it reads sat 0.0017 / black 23.4% / mid 26.2% / white 14.6% / luma 0.398 against the spec's 0.002 / 24.8 / 25.9 / 10.2 / 0.389 -- so the harness is right and **the spec's figures are the PANEL, not the frame**. Measured over the whole composited frame the same reel reads saturation **0.081**, because the blurred backdrop behind a letterboxed panel is built from ungraded source. `g13` as shipped reproduces the spec chain exactly on six samples of a real recording: sat 0.0000, black 28.9%, mid 25.0%, white 9.8%. | **`eq=saturation=0` does not desaturate.** Measured on the same six samples: raw footage is 0.378 mean saturation, `eq=saturation=0` leaves **0.045** and `hue=s=0` leaves **0.000** -- so g07 "Monochrome" has never quite been monochrome. Left alone on purpose, because existing projects reference it; g13 is built on `hue=s=0` and a test names the measurement. **And the order is the grade**: desaturate, curve, then contrast lands black at 28.9% and white at 9.8%, while contrast first -- which is what studio's grade tuple means -- gives 21.4% and 8.6%. So g13's tuple is neutral and the whole chain is its static string. **The drop threshold in the spec misses its own drop**: 10 dB was read off one window against one window, and against the median of the preceding two seconds the real step on that track is 9.9 dB. 6 dB taking the first sustained step answers 17.0 exactly, which is the known answer. **And the whole-BPM snap is a score test, not a distance test** -- over 18 real tracks it snaps 120.0081 to 120 and refuses 133.245, and the span is 0.2 rather than 0.6 because 73.554 snapping to 74 is a quarter-second of drift across a forty-second reel. |
| 2026-10-13 | **The recap, measured on real footage**, v1.65.1 | The first real run of v1.65.0 cut **6m27s from a 52-minute watch-through, 30 moments from 38 rounds**, and the progress bar read "Cutting the recap: moment 11 of 31, eta 84" the whole way -- all of which is right. Three things were not. **Eight chapters in a row read "Lotus"**: a one-kill moment has no name of its own and the match name was standing in for it, so the map name is now a chapter ONCE, where the match changes. **"LAST ALIVE 1v3", "Last Alive", "CLUTCH 1v2" and "Flawless" shared one chapter list** -- `tidy_label` capitalises words and leaves anything with a digit in it alone, so "1v3" survives. **The filename and the title card said 15-23**, Lotus's 13-10 plus Sunset's 2-13, a result neither game had: with more than one match it says "2 matches" instead. | **The output is 1.4 GB for six and a half minutes**, which is 29 Mbps -- a slow upload for something nobody watches at full bitrate. Measured on a minute of the same recording: cq 19 is 25 Mbps, 21 is 20, **23 is 16** and 25 is 12. The recap's final encode moves to 23, still a third above YouTube's own 1080p60 recommendation and a third off the file; the pieces stay at 18 because the join re-encodes them once more and starting coarser is generation loss for nothing. The Rivals highlight keeps 19 -- it is two minutes long and size was never its problem. **And none of these three were findable offline**: 2985 tests passed on the build that produced all of them. A recap is read, not asserted. |
| 2026-10-13 | **The match video becomes a recap**, v1.65.0 (asked: "the resulting valorant match summary is too lenghty there are no transition effects there are no sfx on transitions no intro no ouyto and it took soo much time") | The switch now makes **about eight minutes of the match's best moments, in the order they happened**, with whip cuts and whooshes between them, a hit flash and a hit sound on every kill, a title card over the opening shot, music under the end and the channel outro. `clips/match_recap.py` chooses the seconds and the names; `clips/highlight.py` does the cutting, which it has done for Marvel Rivals since v1.30 and was only ever tied to that game by the two lines that asked a `rivals.Match` for its KOs -- `render()` takes kill times now, so the whole themed renderer is available to any game with a clock. Rendered end to end on the real 78-minute recording: 7 shots, 2m14s out, 54 seconds of encoding, title card and chapters correct. | **The shape was measured against the genre, not invented.** "15 Times Shroud Was a Beast In VALORANT" is 6m32s: an 18-second intro and fourteen moments of 15 to 50 seconds, averaging 28 -- and every chapter is named for the play ("Insanely quick 4K", "3 kills with 4 bullets"), never "Round 7". Three other VALORANT uploads on that channel run 9:58, 10:21 and 12:04. So the target is MINUTES: the old watch-through kept **83% of the recording** (52m01s) and the montage path runs ninety seconds, and neither is the thing people upload. **Chosen by strength, played in order** -- that is what makes it a recap of a match rather than a montage, because the score moves forward and the last moment is the one the match ended on. **And two matches stopped pretending to be one**: a recording with Lotus (won 13-10) and Sunset (lost 2-13) in it produced one file titled "VALORANT 15-23 - loss", a scoreline that never existed, because `merge_matches` flattens every record's rounds into one list. The chapters now carry the map name when a recording holds more than one match, and only then. `clips/match_summary.py` is no longer wired to anything and says so at the top; it is kept because its arithmetic is right and proved. |
| 2026-10-13 | **The match switch shipped unreachable, twice**, v1.64.1 then v1.64.2 (asked: "gove me screenshot where does the valorant match summary button is") | v1.64.0 shipped "Also make the whole match as one video" and nobody could see it: `clip_renderOptions` draws the field on `s.rounds || s.matches`, and the server never put `matches` on a recording's row. v1.64.1 added it to the wrong method. v1.64.2 puts `r["matches"] = bool(prof and getattr(prof, "matches", False))` inside `clips_sessions` -- the method that actually builds the row. Verified against the running v1.64.2 build, not the source: **35 of 72 recordings report `matches: true`** and a headless browser finds the switch visible at the Style step. | **A test that can be satisfied by the wrong function is not testing what it names.** The guard written to stop exactly this grepped the WHOLE FILE for `r["matches"] =`, matched the same line in another method, and passed green while the switch was still invisible -- which is how v1.64.1 shipped a fix that fixed nothing. The guard now slices `clips_sessions`' own body out of the source and reads only that. **And the claim is now checked at the far end.** Both failures were "the source says so" standing in for "the app does so"; the API was never asked. The order is: build, ask `/api/clips/sessions`, THEN say it works. Ten seconds of curl against twenty minutes of a release that changes nothing. |
| 2026-10-13 | **C2 for Valorant: the whole match as one video**, v1.64.0 | The switch has existed since v1.41.0 and reached the job since v1.54.0, but Valorant could not use it and the roadmap named three reasons. All three are gone. **The score was zero.** `rounds_from` built every round with `score_before=(0,0), score_after=(0,0)`, so every YouTube chapter would have read "Round 4 - 0-0" -- worse than no chapters, because it looks like a working feature telling you nothing. Riot gives each round's winner, so the running score is now a tally over them in order. **A round nobody died in vanished.** Its bounds came from its own first and last kill, so an eco nobody contested, or a round won on the spike, was dropped from the match outright. A quiet round is now placed between its neighbours. **And the switch was hidden.** It lived inside the rounds field, which shows only where `rounds` is on -- which means where the SCREEN is read for rounds, Counter-Strike's scoreboard. The spans this needs can come from a match RECORD instead, which is how Valorant knows its rounds and why its profile deliberately leaves `rounds` off. It is its own field now, shown for `rounds` OR `matches`. | **Two different questions were sharing one field**, and that is the whole reason this sat unbuilt behind "the gap is bigger than wiring": "does this game have rounds we can time" and "should the scan read the screen for them" are not the same question, and conflating them hid a feature from the only other game that has match records. **The padding bit back**: a quiet round's span is read as a first and last kill and then padded either side, so the first attempt placed rounds that overlapped their neighbours -- the test caught it, and the padding is a named constant now rather than two numbers written twice. **And three tests in a row refused a half-wired gate**: the page now reads `matches` off a pick, a hand-picked file supplies none, and the exemption had to be written on the right list, in the convention the rest of the page reads by, with the reason. Still not built: the match VIDEO itself for Valorant is now unblocked but has never been cut end to end on real footage. |
| 2026-10-13 | **U20** the reel writes out as a timeline another editor can open, v1.64.0 | `autostream/clips/interchange.py`: **OpenTimelineIO** (`.otio`, which Resolve and the OTIO adapters read) and **Final Cut Pro 7 XML** (`.xml`, which Premiere imports), from the `.reel.json` that was always a project file. One video track of cuts with each clip's source in/out so the media relinks, the song as its own audio track at the reel's offset, and the kills plus the beat grid as markers. Reached from **Export** in the editor's toolbar and from the palette; `/api/studio/export` writes into `clips/timelines`. Checked on a real 38-shot reel: both formats parse, 189 markers, every clip pointing at a real file. | **The sheet is the feature, not the file.** Our transitions, kill effects, grade, lyrics and facecam are ffmpeg filter graphs and no interchange format has a vocabulary for them -- and a speed RAMP (fast in, slow on the kill, fast out) collapses to a single rate because neither format can hold its shape. So `<name>.export.txt` is written beside the timeline saying exactly that, and the page SHOWS it rather than hiding it behind a success toast: what did not survive is the part worth reading, and a toast is gone in four seconds. A silent downgrade is how somebody loses an afternoon at the other end. **And the format is asked, not guessed** -- OTIO on the button, Premiere's XML as its own command -- after a first attempt used `confirm()` with OK and Cancel standing for two formats, which is a dialog that cannot be read. |
| 2026-10-13 | **Four that were written down and left**: the build that half-deleted an install, the window nobody could find, Serif's lost line breaks and Stamp's gradient on a turned box, v1.63.0 | **The build race, which cost a working install tonight.** The guard waits for `AutoStream.exe` to become writable, and that is not the same as the INSTALL being free: the exe was released while `_internal\msvcp140.dll` was still mapped, PyInstaller began clearing `dist\` and aborted part way through -- 31 files where there should be hundreds, and an app that would not start. Retrying picked a different runtime DLL each time. The old install is now cleared by the script itself, with 40 attempts over 20 s, and only AFTER config, secrets, logs and state.json are copied out; PyInstaller then writes into an empty directory. **The window nobody could find.** Launching a second copy logged "already running" and exited, which from the outside is a double-click that does nothing -- and the window it points at may be in the tray or on a monitor that is switched off (the user's was at x=-1086). A second launch now POSTs `show` and the running copy comes to the front. **Serif lost every line break.** `.lower()` turns the ASS hard break `\N` into `\n`, a different tag, and under Serif's WrapStyle 0 that is treated as a space -- so Serif ignored every break the wrap decided and the box width with it. **Stamp's gradient on a turned box**: four bands painted by clipping the word once per colour, with a clip axis-aligned to the FRAME, so a box turned 8 degrees drew horizontal stripes across tilted text; the corners turn with the text now. | **Three of the four were found by using the app, not by reading it** -- the build broke an install in front of the user, the window was reported as "it opens and nothing happens", and the gradient came off a contact sheet. **The Serif one is the exception and the most interesting**: it was found while reading why Serif had ESCAPED the vertical-column bug. It escaped by accident -- its breaks were being destroyed, so there were none to go wrong -- which is the worst way to be correct, because the day the accident stops the bug arrives fully grown. **And the turned clip keeps the unturned output character for character**, which is the only reason it could ship beside the boxes without re-rendering every reel that has none. |
| 2026-10-13 | **The number U19 was gated on, taken** (the plan: "The gate is a measurement, not a review... we have no such number today; take it before starting") | Measured against the live app on a **20-shot reel** (`G03-val-velocity`, 34.6 s, vertical), three runs of each, medians: **nothing changed -> 13.0 s** (13.0, 13.0, 13.1 -- the join alone, and the floor nothing can go under); **one shot's speed changed -> 15.1 s** (one shot re-cut, so a re-cut costs about **2 s**); **the colour grade changed -> 37.1 s**, because that re-cuts **all twenty**. A first render of the whole reel is 37.1 s. The user's own reels were not touched: the project was copied under another name and everything written was deleted. | **The measurement found something nobody was looking for.** "Change the colour grade" was designed as the *join-only* case -- a reel-wide look, surely applied at the end. It re-cut every shot: the grade is a field on each Segment and the cache key is a hash of the whole segment. **So picking a different grade is one of the most expensive edits in the app, 13 s to 37 s, and nothing in the page says so.** Reading the code would have given the opposite answer, and did. **What it means for U19**: a keyframe lane forces a shot to be segmented, and a segmented shot cannot come from cache -- so keyframing one shot costs ~2 s, five costs ~10 s, and keyframing everything costs the same as a grade change. The lane should exist only on shots that have one, which is what the plan's own mockup draws. |
| 2026-10-13 | **The montage looked like a stutter: a clip cut back to itself half the time**, v1.62.0 (asked: "rank it like a youtube professional valorant montage") | A reel was built from the user's own 44 clips and then reviewed frame by frame off a contact sheet. **21 of its 40 cuts went from a clip straight back to itself** -- the same corner of the same map, seconds apart in real time -- and it had **one hero moment in 41 shots**. Three causes, each found in the model rather than guessed: **(1) a "sequence" was a whole CLIP**, so a two-minute clip with twelve kills contributed six of the strongest bursts and they played back to back; a sequence is now a BURST, which is what "a TRIPLE KILL never shows two of its three kills" actually meant. **(2) The strongest moments cluster anyway**, so `spread_clips` puts a different clip between any two neighbours from the same one -- a forward pass, then a swap for the clash a forward pass cannot reach (the last pair has nothing left in front of it). **(3) A moment could only be a hero if it carried a caption**, and a caption is set only on the last burst of a clip that gave two or more kills -- which a headshot montage almost never has. That caption existed to be drawn by the Text slam, and the slam was removed in this same release at the user's word ("the effect ... is shit"), so the coupling had nothing behind it at all. Measured on the same 44 clips: same-clip cuts **21/40 -> 0/41**, heroes **1 -> 7**. | **Removing the slam is what exposed the hero bug**: the caption was dead the moment the effect that drew it went, and the dead field was gating a feature. **And the fix broke an invariant the tests caught**: ranking bursts separately let a later, stronger burst outrank an earlier one from the same clip, which lets a shot replay footage a shot before it already showed -- the thing the follow-up fold exists to prevent. The spread now moves the PLACES and puts each clip's bursts back into the order they happened. **What a contact sheet is for**: none of this was visible in the project JSON, and all of it was obvious in eighteen frames side by side. **Still not done from the same review**: the shot-length curve barely moves across the reel (1.84s -> 1.20s, which is a drift rather than a build), there is no title card, and the 9:16 crop cuts off the kill feed -- in a kill montage, the confirmations. |
| 2026-10-12 | **U18, part one: the timeline grows a hand** -- Roll, Razor, J/K/L, in/out and marks, v1.61.0 | **RIPPLE WAS NOT BUILT, and that is the finding.** The plan asked for four tools; reading the model showed this timeline has no gaps -- the shots are a sequence and the reel is as long as their sum -- so shortening a shot ALREADY pulls everything after it back. A ripple tool beside the trim that already ripples would be two names for one behaviour, and a test now asserts no such command exists, with the reason. What the timeline genuinely lacked was **Roll** (the join moves, one shot gains what the next gives up, so the reel keeps its length and every kill after the join stays on its mark) and **Razor** (one shot cut in two, the kill going with the half it happens in, neither half under a beat, the new join a hard cut). Both are also modifiers on the drag that already exists -- Ctrl rolls -- and **Escape always returns to Select**, so nobody is stranded holding a tool. Then the navigation the editor had none of: **J/K/L** as a real shuttle (1x, 2x, 4x, 8x, slowing and reversing through J, K stopping dead), **I/O** in and out points drawn as a band over the ruler, and **M** to drop a mark. 9 tests, scenarios 6.45-6.49. | **A plan can be wrong about the code it has not read yet**, and saying so is cheaper than shipping the fourth tool. **The roll/trim choice is fixed on the press**: read live, letting go of Ctrl halfway through a drag would turn a roll into a trim under the hand and the reel's length would jump mid-gesture. **In and out are a PLAY range only**, as the plan ruled in writing -- the change list exists to say what has not reached the video, and a part-render would let it claim the video matches the timeline when it matches a slice; a test asserts nothing in that path can reach a render request. **Marks live on the project**, not on the page: they are notes about the reel, so they survive a reload and can become chapters later. **Still to do, and named rather than left looking done**: rate stretch, and more than one shot selected -- the riskiest piece, because `sel` feeds the inspector, the frame handle, move and delete, and the LIBRARY already has a different multi-selection that looks identical and means something else. And no browser test yet: razor and roll are drag-and-click, which is exactly what offline tests cannot see. |
| 2026-10-12 | **U17** redo, and a history you can step back through, v1.60.0 (asked 2026-10-11) | `studio_undo()` POPPED the stack: the step came off and was gone, so a Ctrl+Z pressed once too often could not be taken back, and nothing anywhere could show what had been done. It is a cursor now, kept as two stacks -- `undo` holds the states behind you and `redo` the states ahead, and a step MOVES between them instead of being destroyed. **Ctrl+Z** back, **Ctrl+Shift+Z** forward, read in one handler so Shift cannot end up on another scope's key. Both buttons name the step they would cross ("Undo: shot 7 sped up"), in the title rather than the label, because a label that changes width makes the toolbar jump on every edit. A **History** panel lists every step with your place marked; the steps you have undone stay on it, and clicking any step walks to it. Crossing a step happens in exactly one function, `studio_step`, so back and forward cannot drift apart -- two implementations and a redo would eventually stop reconciling the change list while an undo did. 4 tests, scenarios 6.42-6.44. | **The plan's one correction held.** It proposed building the history out of labels `studio_change` "writes and throws away"; that stopped being true in v1.52.0, where the labels became the change list itself. So the history reads those labels rather than inventing its own -- one set of names, two views -- because two lists over one set of edits would eventually disagree and then neither could be believed. **Jumping to a step crosses every step between**, rather than restoring that state directly: a direct restore would leave the two stacks describing a history that never happened, and the change list reconciled once at the end instead of at each step. **And the registry caught a real mistake in this very change.** Two of the new actions were being assembled from a variable (`data-act="' + act + '"`), so nothing reading the source could find them -- the same failure mode as a route built from pieces, which the wiring test has caught before. U16's rule failed the build until they were written out literally. That is twice in two days. |
| 2026-10-12 | **U28** the lyric boxes are drawn on the picture, and the lines are dealt round them, v1.59.0 (asked 2026-10-12: "instead of giving the user the size and width option as main option ask them to make a BOX on the screen ... the first line appears on the first box then the second line appears on the second box ... the 4th lyrics again on first") | Width and Size were two numbers describing a rectangle nobody could see. A box **is** that rectangle, drawn where the words will be: drag on the picture to make one, drag it to move, its corners and edges to resize, a knob above the top edge to turn it (5-degree steps, Shift for any angle). Up to six, each wearing its number -- because the number is the deal order, not decoration. `lyrics.boxes` holds each as a CENTRE plus a size in shares of the frame, so a box keeps its place and its proportions when the reel is made 9:16 instead of 16:9. The server deals row `i` into box `i % n` and fits the words to it in both directions, per box: on four lines and three boxes the type came out 85, 70 and 95px, the fourth line back in the first box at 85px. All five looks place into them. The preview shows it without a render -- preview and render are one `prepare()` -- and every drag is one line on the change list and one press of undo. Width and Size stay, folded away, as what governs a reel with no boxes, and the panel says the boxes are in charge once there are any. 5 tests; scenarios 6.38-6.41. | **A box has to beat the floor, not obey it.** `REVEAL_MIN_SCALE` (42% of the look's own size) exists so Stamp still looks like Stamp, and it is why v1.58.0 could only get a quarter-width box from 13 rows to 12. Somebody who has DRAWN a rectangle has already traded that away -- they said where the words go and how much room they get -- so inside a box the only floor is legibility, 28px on a 1080 frame. That is what makes a small box work rather than bottom out, and it is the difference between a control that is honoured and one that is a suggestion. **The ordering fault could not come back here**: the box is fixed and the type gives way, so there is no order in which the wrap and the shrink can cancel each other -- which is exactly what went wrong the release before. **What the registry bought, one day in**: three new controls could not be added without their rows in `ui/commands.py` and the surface catalogue, because U16's own rules fail the build otherwise. That is the point of it. **Not done**: a box layout cannot be saved as a preset across reels, there is no per-box typeface or colour, and Stamp's gradient clip is axis-aligned, so a turned Stamp box has its four bands running across the frame rather than along the box. And no browser test yet -- a resize handle wired to nothing passes every offline test there is. |
| 2026-10-12 | **The lyrics came down the middle of the frame instead of across it**, v1.58.0 ("still it is being placed one word in one line, I want each line to go from left to right ... the whole lyrics style is busted") | Reported with a screenshot of a 9:16 preview: a sung line drawn as a vertical column, one word to a row. **Not a unit mismatch** -- the Width control's fractions are right and `settings()` clamps them correctly -- but an ORDERING fault in `build_ass`. The line was wrapped at the box's own character budget and `_shrink` was then handed rows that already fitted, so it returned 1.0 and **the type never came down**: Stamp kept its 250px and the line was shredded to make it fit. Measured through `build_ass` on a real lyric line, 1080x1920: stamp/typewriter **at the default full width** was 8 rows at 250px, a block **2400px tall in a 1920px frame**; at a quarter box, 12 rows. Now the wrap is given the characters the type fits once it HAS shrunk (`budget / REVEAL_MIN_SCALE`) and the shrink brings it there: **4 rows at 107px, 514px tall**, reading left to right. Glow 6 rows -> 3, Scrawl 8 -> 4. **A second fault in the same screenshot**: Stamp paints its four-band gradient by clipping the word four times, and the clip was one row's height around the centre -- so a wrapped unit drew its middle row in the gradient and every other row flat in the darkest band. The clip now spans the rows actually drawn. The `look` and `word` reveals never reach the wrap and are byte-for-byte unchanged. | **Two existing tests passed throughout, and one of them asserted the bug.** Both called `_regroup` and `_shrink` directly, and the fault was in the ORDER the two were used in, which neither could see; `_shrink` even looked healthy in isolation because its own test fed it an unwrapped row. The new test goes through `build_ass` -- what the preview and the render both draw from -- and asks the only question that matters: **does the block fit the frame it is drawn in**. **Preview and render were never divergent here**, unlike U13: one `prepare()`, one content-hashed cache file, one `.ass`. The user's own cached script (`Fontsize 107` = 250 x 3/7, alpha `&H4D`) is what pinned the settings they had. **Open, and deliberately not fixed blind**: at a quarter box `REVEAL_MIN_SCALE = 0.42` binds -- Stamp's floor is 105px and a quarter of 1080 is 270px, about five characters -- so a sung line physically cannot read across a quarter-frame box in Stamp's type. Either a narrowed box lowers that floor, or the narrow widths are not offered for the big-type looks. Also noticed: serif's `.lower()` turns the hard break `\N` into a soft `\n`, which under its `WrapStyle 0` libass treats as a space -- so serif ignores the box for wrapping entirely, and escaped this bug by accident. |
| 2026-10-12 | **The render that looked stuck: 2.5x of it was a blur nobody could see, and the bar parked at 95%**, v1.58.0 ("stuck at 95% for so long") | v1.56.0 made an all-cached render stop reporting 0%; it then reported **95% for four minutes**, which is the same silence a notch further along. Two fixes, both measured rather than read. **(1) The blur-to-focus opener was 60% of the render.** `i05` builds `split`/`gblur`/`blend=all_expr=...`, and the expression resolves to exactly stream A once `T >= 1.2 s` -- but a per-pixel `all_expr` is still evaluated on every frame of the whole reel, 1080x1920 x 4243 frames for a 71 s reel, ~98% of it thrown away. Measured on 10 s of a finished reel, decode plus `h264_nvenc` each time: **2476 ms** with no filter, 2532 ms for the `gblur` alone, **28308 ms** for the blend ungated, **6019 ms** gated with `enable='lt(t,1.2)'`. Ungated against gated over the first 4 s -- the blend window and the pass-through either side of it -- is **PSNR inf on all three planes**, bit-identical. The 262 s render of that reel should come out around 100 s. **(2) The join now reports itself.** It was one `subprocess.Popen` with `stdout=DEVNULL` and no `-progress`, so the longest phase of a render was the only one nothing could report on. It runs with `-progress pipe:1 -nostats`, a reader thread takes ffmpeg's own `out_time` clock, and `snapshot()` counts the join in the seconds of reel it has produced rather than as one unit of work -- and never reads 100 until the job is actually finished. | **The 95% was honest arithmetic about the wrong units.** 47 shots plus 2 made the join "2 of 49" when the join was 100% of the wall clock; a unit of work is only a unit if the units are comparable. **And the thing that cost the time was not the thing being changed.** The user was editing lyrics, the lyrics cost ~20 s of the 262 s (`ass` is 2.8 s per 10 s), and the 160 s nobody had looked at belonged to an opener whose output was provably identical to doing nothing. Reading the filter graph would not have found it -- the expression is correct -- only timing each filter separately did, which is the clip-bug rule applied to render time. Diagnosed in another session on the same working tree; the measurements are theirs. **Still not done**: the join's remaining cost (concat + libass over every frame + watermark + ducking + a two-pass loudness that walks the reel twice) has not been measured per stage, and a single-pass loudness is a hypothesis, not a finding. And two renders that genuinely died today did so within seconds of "main window hidden - still running in the tray" (ffmpeg exit `0x40010004`, DBG_TERMINATE_PROCESS -- killed from outside); the correlation is strong, the mechanism is unproven, and it needs deliberate reproduction before anybody "fixes" it. |
| 2026-10-12 | **U16** every action has a name, and a list you can search, v1.58.0 (asked 2026-10-11, from the ArtCraft specifications) | The page declared **147 distinct `data-act` strings** and eight key bindings in one `keydown` block and could enumerate neither, which is the whole reason it had no palette, no key sheet and no rebinding. `autostream/ui/commands.py` is now one table of **162 commands** -- `{id, label, scope, act, args, keys, palette}` -- covering every one of those 147 actions, served to the page inline and to the browser tier at **`/api/studio/commands`**. **Ctrl+K** opens a list that searches by name and by code, groups by scope with the pane you are in first, puts what you last ran at the top, and shows each command's key; **`?`** prints a key sheet generated from the same table. A command runs by pressing the control the page already has for it, found by its `data-act` and data attributes -- nothing is reimplemented. **A command that cannot run says why**, in words, on the row and in a toast when its key is pressed: "A reel keeps at least one shot, and this is the last one". Four offline rules in `tests/test_studio_commands.py`: every rendered action has a command and every command a rendered action; no key twice in one scope; no binding naming a command that does not exist; and every declared key is one the page's handlers actually read. Scenarios 6.34-6.37. | **The old `keydown` block still runs every key, deliberately.** The plan said the registry must not delete it until a test replays every key in every pane state, and that test is the browser tier's, which has not run -- so the registry *declares* the keys (which is what the sheet and the list print) and the handler still *reads* them, with a fourth rule holding the two together. One of those two is going to drift, and the rule is what makes it loud rather than silent. **The palette was the cheap part; the labels were the work.** 147 machine names had to become sentences somebody would search for, and about half the actions turned out to be parameterised -- seek to this x, pick that clip -- which belong in the registry (it must be complete) and out of the list ("Seek" with nowhere to seek to is not an offer). Hence the `palette` flag. **And the delete guard moved.** "A reel keeps at least one shot" was a condition inside the keydown block where nothing else could see it; it is now in `STUDIO_WHEN`, which the key, the button and the list all read -- which is what U18's `enabled()` is for. |
| 2026-10-12 | **U27** the lyrics get a box, a size and an opacity, v1.57.0 | Stamp draws a word at 250px -- most of a 1080 frame, fine for "YEAH" and a wall for "YEAH HELL", and worse once a reveal puts a whole line in it. Three steps-not-sliders beside the look: **Width** (the share of the frame the words may run across -- they wrap inside it and the type comes down until they fit, never below 42% of the look's size), **Size** (0.5x to 1.6x) and **Opacity** (solid down to a ghost). | **Opacity could not be a prefix.** ASS carries transparency in the top byte of every colour AND in `\alpha`, and the looks animate it themselves -- Serif fades each word in, Glow fades the line out -- so dimming the style alone is undone the moment an animation runs to `&H00&`. It moves the opaque END of every animation instead, and leaves a fade that starts invisible starting invisible. **And the default had to be provably untouched**: a test asserts every look at full width, full size and solid draws byte-for-byte what it drew before any of this existed, because a setting that silently restyles existing reels is worse than no setting. |
| 2026-10-12 | **U25, U26** the lyrics arrive how you ask, and a long render stops being thrown away, v1.56.0 | **The reveal was welded to the look** -- Stamp was one word at a time because Stamp was, Caption whole phrases because Caption was -- so whole lines in Stamp's type could not be asked for. A third control beside Look and Typeface: the look's own (the default), one word at a time, a whole line at a time, the line building up, and a typewriter. **The render that "never started"** was starting -- five times in twenty minutes on the user's own machine -- and two things hid it: the page waited a flat 2.5 s after an edit while `yield_auto` throws the running render away for the newer one, so on a 47-shot reel whose render takes 4m18s a steady editor restarted it forever; and `total` counted only the shots left to cut, so an all-cached reel sat at 0% through the whole four-minute join. The wait is now a tenth of what the last render on that reel cost, capped at 20 s and learned from the render itself, and cached shots count towards the bar. | **The reveal was cheap because every look already draws units.** Changing what a unit IS leaves each look's type, colour and motion alone -- a typewriter in Caption's face, whole lines in Stamp's. Two looks aggregate a row themselves and produced "never never gonna" until each unit became a row of its own, which is the sort of thing only running it shows. **And "it is not working" meant "I cannot tell that it is working"**: nothing was blocked, no setting was off, no exception was thrown. A four-minute job reporting 0% and silently restarting is indistinguishable from a job that never ran -- the bug was in what the page said, not in what it did. A diagnosis that had gone looking only for a refusal would have found nothing and called it unreproducible. |
| 2026-10-12 | **U22, U23, U24** the order is asked once, the examples are cut from clips you starred, and the Studio is three tabs, v1.55.0 ("where is the option ... about the order of the clips"; "use a different more clean GIF and make it a little high quality"; "I don't know from which folder, from which run the current clips are selected"; "3 pages are being squeezed in together") | **The order** was asked twice: three buttons in the Make dialog that only re-sorted the clip list in the page, and the six real arrangements in the strip at the foot of the Clips tab -- so **Best order**, which puts the aces and multi-kills on the song's biggest hits, could not be reached from the dialog where the reel is made, and went unnoticed for two releases. One control now, in the dialog, drawn as cards with their sentence, Best order marked recommended and Perfect fit carrying its ~30 s cost; the strip and the dialog share `studio.arrange`. **The examples** on the effect cards are cut from clips the player has starred rather than whichever two are shortest, at 640px/30fps/CRF 26 rather than 480/24/CRF 30, and `build()` records what it cut from. **The picks** are counted on every folder card, run row and match heading, a band names the runs a reel's clips came from and opens them, "Show only these" is a real filter, and the tray says "from N runs". **The page** is three tabs -- Clips, Reels, Looks -- because it was carrying three jobs in one scroll. Browser tests 6.28-6.31, 30 of them. | **A control nobody can see is a feature nobody has.** Best order was built, tested, released and written up in v1.52.0, and the user asked for it again twice -- the second time after being shown where it was. Two words on a button in a strip below ninety reels is not an offer. The card with its sentence is, which is why the picker's cards worked (U1) and this did not. **The quality numbers were measured, not chosen**: a 3.6 s card is 121 KB at 480/CRF30, 353 KB at 640/CRF26 and 560 KB at 720/CRF24, and a card is 360-480 CSS px on screen, so the middle one; the whole set of 562 goes 68 MB -> ~195 MB. Also found while measuring: a tie on duration fell through to folder iteration order, so two equal-length clips could swap between runs and silently re-cut every card. **And the empty Reels tab was a dead end the browser found** -- a pane that opens on nothing, which is exactly what splitting a page can introduce; it says what to do instead. |
| 2026-10-11 | **U15** the Studio library is a drill-down, v1.54.0 ("show only folders, and upon opening the folder show the Valorant matches, and in that the clips") | The library opens on **a card per game** -- a four-still mosaic, the clip and run counts, plus ★ Favourites -- instead of every clip at once: 339 tiles in one pane on the developer's machine, 42 runs across 4 games. A folder opens on **its runs**, newest first, each with a chip per match in it; a run opens on **its clips, grouped by the match each was cut from**: map, mode, the score coloured by the result, the player's K/D/A and where the match starts in the recording, with `Select match` beside `Select run` and clips outside every match in a group of their own. Breadcrumbs walk back up, the open folder and run live in `studio.game`/`studio.run` so a rebuild of the pane keeps your place, and the search still answers from the whole library from any level. Server side: `_match_groups()` in `clips/studio.py` and `valorant_match.one()`, which reads a single record rather than parsing the 41 MB cache -- the whole library call is 0.14 s on 42 runs. 8 unit tests, 13 browser tests (scenarios 6.24-6.26). | **Nothing in it needed detecting: both halves were already on disk**, and checking them against each other is what proved it. The spans are in each run's `session.json` (`demo.matches`, written when its kills were aligned) and the map, mode and score in the record the Clips page fetched for U2 -- assigning the 10 Oct run's clips by start time gives 10 + 4 + 15 + 9 = 38, every clip placed, with 18 / 23 / 24 / 27 kills per group, exactly Riot's numbers for Lotus, Drift, Haven and Piazza. **The sweep's floor is about what is *rendered*, not what exists**: clips two clicks in stop being enumerated, so `REACHED_FLOOR` would have failed for a page that was working perfectly — the fix is two new sweep states that open a folder and a run, never a lower floor. Two things the folder view made visible and neither is fixed yet: **20 of the 42 folders are single imported clips sitting in "Other"**, all of them Valorant, because an import writes no `game` (and the same ten are there twice from two import runs); and a map key `MAP_NAMES` does not have (`Plummet`) shows Riot's internal name on the chip. Also: the control table in UI-SCENARIOS said 190 controls and 121 on the Studio; it is 226 and 147, re-counted. |
| 2026-10-11 | **U21** the effect picker stays open until you dismiss it, v1.54.0 ("when I select any effect to include or exclude the page goes back to the timeline ... so to add 4 effects I have to open the page 4 times") | A single choice -- an ending, a transition, a speed, a colour, a camera move -- closed the dialog on the first click, by design from U1 ("one choice applies on a click"). It still applies on the click, and now the dialog stays up: the tick and the stage button move to what is in use, and **Done** is what closes it. **Cancel still means what it says** -- for a choice already applied it puts back the one that was there when the dialog opened, through the same edit path as any other, so the change count simply returns to what it was. Two browser assertions added to the U1 and stage tests. | **"One click, one choice, done" was right about the click and wrong about the dialog.** Choosing is also comparing -- the whole point of the big stage added in v1.53.0 is to tell two endings apart -- and you cannot compare two things one modal at a time. The many-at-once lists already worked this way; the single ones were the odd case, not the rule. |
| 2026-10-11 | **C2's switch had never worked**, v1.54.0 (found while answering "was the Valorant match summary ever implemented?") | The Clips page's "Also make the whole match as one video" has sent `match_summary` since v1.41.0 and `webui.clips_run` never copied it out of the request body, so `jobs.ClipJob`'s `opt.get("match_summary")` was false on every run ever started from the UI -- for Counter-Strike too. One line in `clips_run`, and a test that pins **both ends** (the page still sends it under that name; the server still copies it into `opt`). | **A browser test that stops at the request body is half a test.** `test_ui_clip_stages` asserted the page put `match_summary: true` in the body and never asked what the server did with it, so a feature nobody could use stayed green for a year. Where a page flag crosses to the server, pin both sides. Valorant's half of C2 is still not built, and is three things rather than one: real round scores (`rounds_from` leaves them `(0, 0)`), round bounds that do not come from the first and last kill, and a switch its profile currently hides. |
| 2026-10-11 | **The preview shows the lyrics and the 9:16 blur, and the effect picker shows the effect big**, v1.53.0 ("when I change the lyrics style it is not shown until it is re-rendered"; "with 9:16 and fit, the bands should be blurred, not black"; "put the actual preview in the centre and big so that it is easy to spot the difference") | All three were what the page shows before a render. **Lyrics**: the render's own subtitle script drawn alone into a transparent VP9 video and laid over the preview on its clock (`lyrics.overlay`, `/api/studio/lyrics/preview`); libass cannot draw alpha, so the script is drawn twice on black, as it is and all white, and divided -- 2.3-2.8 s for a 62 s reel, against a render of 20-odd. **Blur**: the render already put a fitted 9:16 over a blurred copy of itself; the preview used object-fit:contain on black, and now draws the picture onto a small canvas behind it, blurred by CSS. **Picker**: the list is a column of playing rows and the stage takes the rest, centred and 16:9, with a "Use this" / "Add it" button; and since four overlay cards (fine and coarse grain, fine and wide scanlines) were measured indistinguishable at the card's 360-480 px, the one on the stage is cut again at 1280 wide on demand (`examples.make_large`), one at a time, never while live, recording or rendering. Browser tests 6.21-6.23. | **A bigger box is not a clearer effect.** Moving the preview to the middle without a sharper file would have enlarged the same blur; measuring the cards first is what showed the file was the problem. The preview still leaves out the colour grade, the kill effects and Stamp's grey -- the tag says so. |
| 2026-10-11 | **The preview had no play bar**, v1.53.0 ("I changed the outro, then the auto rendering applied, but in that state the on screen play back option disappeared") | From an edit until the render catches up the player is the preview -- two `<video>`s swapped at each cut -- and the rendered video, which carries the browser's bar, is hidden. So every edit took play, seek, mute and fullscreen off the picture. The preview now has a bar of its own over its foot: play/pause, time, a seek on the reel's clock (it lands on the shot the timeline has there), mute, fullscreen of the whole player (a render finishing under it stays in it); a click on the picture plays and pauses. The app's volume and speed knobs reach it too -- its players opted out of `shell_knobApply`, which wrote over the shot's own rate and the project's game level, and the choice is multiplied in instead. Browser test 6.20 presses each control. | **A second player is a second set of controls to keep.** The preview was measured for cuts and arithmetic and never pressed as a player; a hidden element's controls go with it, and no test noticed because none looked for them. |
| 2026-10-11 | **The Studio's change count counted clicks, not changes**, v1.52.0 ("if I select and unselect a setting, the changes count increases") | The list of what is not in the video was an append log: every edit pushed a line or bumped its ×n, and only a render or an undo took one off. A switch turned on and off again was "Apply 2 changes" to a project identical to the video. Now it is a comparison: the project the video was rendered from (or opened as) is kept as `studio.base`; each line remembers the fields its edit changed (`studio_diff`, key paths such as `shots.2.camera`); after every edit, undo and server answer, a line whose fields are all back to `base` leaves. One line counts one, however many clicks -- a slider, a nudge button pressed five times, and the same field reached by two controls are each one thing. A line set back by hand and brought back by an undo returns under its own name; an undo past the render still says so. What the server does in answer to an edit (a speed that trims the shot) is pinned to that edit, so putting the speed back does not claim the video matches while the trim remains. Lines that cannot be compared -- a failed or cancelled render, a deleted reel, a camera video attached, a rebuild from the clips -- stay until a render, and while the shots are not in the rendered order no shot's line is dropped. Browser test 6.13 drives it: vignette on (1), off (0, the button stops saying Apply), two settings with one undone (1), a shot's camera move changed and put back (0) -- read off the card, the button and the badge over the player. | **A count that is put on a button has to be a fact about the video, not about the session.** Both ways it can be wrong are not equal, so the fallbacks all lean one way: when a line cannot be compared it stays, because "1 change" over a matching video costs a render and "the video matches your edits" over a stale one costs a published reel. |
| 2026-10-11 | **Longer reels, every kill kept, and a best order**, v1.52.0 (the user's `dwayIR`: 25 clips and a long part picked, a 43 s Hype reel with 11 clips "left out to fit the reel's length") | **Root cause, from the project itself**: `song_offset` 6.9458 has four decimals, and only the Song tab's `apply_song` rounds to four (the planner rounds to five; re-planned, dwayIR gives 6.94576). So the part was chosen on the Song tab after the plan -- and that path kept the start, never stored `part_end`, could only take shots away (`fit_to_part`), sent the reel's own seeded marks so nothing was ever re-planned, and reopened the tab on the reel's length. "Rebuild with this style" also re-planned without the part. **And a second bug under it**: even a part that did reach the planner was cut at the style's pace -- a 93 s part in Hype came out **62.7 s** while the note said the run-ups had been lengthened to fill it. Now: the part is stored, kept by a new style and by the Song tab, and a Song-tab part longer than an unedited reel re-plans it (hand marks and edited timelines are left alone, and say so). The Make dialog gains **How long** (*The style's length* / *Fill the song part I picked* / *Every clip I chose*) and **Keep every kill** (short run-ups start on the clip's first frame or are slowed, still moments stay in, kills close up to fit a length; a part too short even then leaves the weakest out and says why), and the arrangements gain **Best order** (`rulebook.best_order`). Every kill of a clip in the reel that is not shown says why (`selection[].kills_out`, a "Kills not shown" fold). Measured on dwayIR (old → new, every case 0 replayed footage): as saved 42.8 s, 14/25 clips, 30/42 kills -- unchanged by default; 93 s part 62.7 s → **91.4 s**, 41/42 kills (42/42 with Keep every kill), 37/38 on marks; Every clip + Keep every kill **58.7 s, 25/25 clips, 42/42 kills**, 37/40 on marks, rendered as `dwayIR_long.mp4` and checked by eye (kill counter reaches x42). Aftrhrs: Hype on a 105 s part 65.7 s → 105.2 s; Every clip + Keep every kill 49/49 kills, 27/27 clips. Best order: impact against the hit it lands on, rank correlation +0.08 → +0.75 (dwayIR), +0.29 → +0.38 (Aftrhrs). Found on the way: `_fit` read a ramped shot cut exactly to its footage as 5 µs over it, took a whole beat off its tail, and slid every later kill 0.55 s off its mark (Aftrhrs Best order: 17/43 on marks → 42/43). 14 unit tests, 2 browser tests. | **A length the user picks has to reach the cut, not just the selection.** The planner's target only decided *which* moments went in; `apply_marks` on the style's gap decided how long the reel was, so every length rule upstream of it -- the part, `_lengthen_run_ups` -- was being undone downstream. Also: a song whose loudness barely moves across the reel is not a signal to order by -- ranked, its noise put Aftrhrs's big moments worse than the plain build did, so where a measure varies under 20% the build's arc stands in. Not built here: the slower exact arranger (`arrange_fit.py`) another session is researching. |
| 2026-10-11 | **Studio: an edit plays at once, and the render does itself** (asked: "deleting a clip from the reel means marking it, waiting 10-20 s for the render, then checking -- make it fast"); shipped in v1.52.0 | **Instant preview**: whenever the rendered file is not the project on screen, the player plays the timeline straight off the clip files -- two `<video>`s swapped at each cut with the next shot cued and decoded in the hidden one, each shot from the source second and at the speed the render uses (`derive()` now carries each shot's `freeze`; `studio.preview_at()` is the arithmetic and the page's `studio_pvAt` is held to it at 30 reel times by the browser test), the song started at `song_offset` + reel time, game and music at the project's levels, vertical cropped like the render. A label over the picture says the effects and colour come with the render. **Background render**: 2.5 s after the last edit the real render starts by itself (`/api/studio/render` with `auto:true`, a `StudioJob(auto=True)`); a newer edit or Render replaces it (`Runner.yield_auto()` cancels and waits; finished shots stay cached), a render the user started is never displaced, and `webui.studio_auto_held()` refuses it while live (any phase but IDLE), recording or cutting clips -- checked by the page from the status poll and again by the server. When it finishes and matches the project the edits are settled and the player changes over at the same second; no toast. Setting `clips.auto_render` (on), switchable beside the player and in Settings > Clips. **Measured in Chromium against this checkout**: delete -> preview updated **16 ms**, the shot after the new cut decoded **56 ms**; a cut played **+5 ms** from its place; the background render began **2.5 s** after the delete, took **~1 s** (2 shots reused), and the rendered file was in the player **4.7 s** after the delete -- against "press Render, wait 10-20 s" before | **The render stops being a step.** What the user waits for is now the preview, which is instant; the render is something that has usually finished by the time they have watched it. Limits, named: the preview has no effects, grade, transition blends, text, lyrics or intro clip (the intro is joined in front of the render and the preview starts at reel zero); a slow disk can make the first frame after a cut late when the next clip had not decoded yet (the cut log records `cued` and `ready` for each); playback rates under 1/16 are shown as a held frame |
| 2026-10-11 | **"Perfect fit (slower)"** arrangement in the Studio (asked: an order where kills and beats look good and no clip of 3-4 kills misses one); shipped in v1.52.0 | `clips/arrange_fit.py`, reached from `studio.plan()` when the arrangement is `fit`. Every kill is an anchor (on a song hit) or a rider (plays on in the shot before); an exact dynamic programme over (kill, anchor, hit) for each clip order, every hard rule a feasibility test on one cut, each shot planned through its own speed's time map; simulated annealing over the order, 400 tries, no clock. Copies the drop reel's fourth-kill-on-the-drop and the half-speed build over a quiet intro. Re-planning five of the user's reels: clips kept 14->25 of 25 (dwayIR) and 17->27 of 27 (Aftrhrs), kills of 3-4-kill clips 10->11 of 11 and 17->18 of 18, every shot's kill on its mark to the frame, no footage twice, no short run-up; Can't Hold Us (velocity) 44.5 cuts a minute against the ordinary plan's 44.1; 9-24 s to plan. Unit tests incl. the programme against brute force; browser test 6.19. | **The ordinary planner loses kills because it decides in stages that cannot see each other** -- select, order, walk, then marks -- and repairs the collisions afterwards. Measured, the programme alone (0.1-0.3 s) already keeps every kill; the search only improves look-alike neighbours, riders on hits and big hits, so it could later replace `_hit_slots` + `apply_marks` in the normal plan. Also found: `drop_still` drops real kills made holding an angle (dwayIR's quadra, checked by eye); the fit keeps them in 3+ kill clips. Open: hype on a 74 BPM song (ambiforcash) cuts slower than the ordinary plan, 30.7 vs 38.3, because a one-beat minimum run-up there is 0.82 s. |
| 2026-10-11 | **A reel's opening quadra showed two kills twice and missed the fourth**, v1.51.2 (the user's `Aftrhrs_fixed`) | Re-planned from the project with main and measured with `derive()`: the quadra (kills 3.567, 5.467, 17.6, 18.433 s into the clip) became three shots on marks 3.30, 7.70 and 11.01 s. **Twice**: the first two kills were 1.90 s apart in the footage and 4.40 s apart on the marks, so the opener ran on past the second kill to its cut (source 0.26-6.87) and the follow-up started at 4.37 inside it -- 2.20 s, the second kill among them, played again; the reel's frames show the same ammo count (15, 14) at 5.0 s and at 7.5 s. **Missed**: the climax shot rushed in at 2.2x (s04), froze 0.75 s on the third kill (h02) inside a 1.10 s tail -- a freeze replaces footage -- so 0.11 s played after it and the fourth, 0.83 s on, never appeared; the ramp would have rushed it at 2.2x anyway. Now `apply_marks` folds a same-clip follow-up into the shot before when the marks are further apart than the footage between the kills (the mark passes on), and where it cannot fold moves the cut to where the footage meets and lets the kill land early; a mark too soon after a shot's own later kills goes to the next shot; `pieces()` holds a ramp out of the kill at real speed until the shot's own kills have played; `_own_tail` and `_span` count the freeze. The same re-plan: 38 of 38 kills shown once, against 36 (and one twice); 32 of 32 kills on their marks; no shot without a run-up, against one. Rendered as `Aftrhrs_fixed2.mp4` and checked by eye. 5 tests. | **Not caused by v1.51.1**: the original `Aftrhrs` (planned before the emblem snap) already had a shot whose source 0.20-7.35 replayed both of the first two kills. The rule the run-up code already stated -- never into footage another shot shows -- was enforced by `_lengthen_run_ups` only, never by `apply_marks`, which is where every song-cut reel's lengths are actually set. The same pass found a third silent loss: a triple whose next mark came 2.20 s after its first kill lost its third kill to the cut. |
| 2026-10-11 | **Kills off the beat in story-style reels of recorded matches** (the user's `Aftrhrs`), v1.51.1 | The beats were right: all 34 marks sit 0-50 ms after the song's beat grid. The kills were not: clips from a run with Riot's record carry the server's kill time, and the Studio skipped the emblem check for them, so a kill landed on its beat by Riot's clock while the kill on screen came -0.17 to +0.53 s later (median +0.13). Each recorded kill now moves onto its own emblem when one is within -0.35/+0.70 s -- one emblem per kill, nearest pairs first, nothing dropped or added. Re-planned and rendered from the same clips: on shots whose effect does not move the emblem, the visible kill lands 6 of 8 within 71 ms of its beat, against 2 of 6 before. 4 tests. | **Why hype and velocity looked right**: their kills carry a zoom punch, a flash or a freeze ON the beat, and the eye reads the effect as the kill; story and clean have almost none, so the game's own emblem is what is seen, and it was late. The check had been skipped for recorded clips because two kills half a second apart share one emblem -- matching one-to-one keeps that safe. |
| 2026-10-11 | **Valorant headshots, and a "Headshot kills only" reel**, v1.51.0 | `clips/headshot.py` reads each kill already found -- three frames of the feed band a moment after it, no scan -- for the crosshair icon Valorant puts in a headshot's row, matched against a template measured from the player's recordings. A clip job stores it on each kill (`hs` in session.json), as does marking an imported Valorant clip; the Studio's tiles say "N kills · M HS", and the Make dialog offers **Headshot kills only** with what it would keep. Ground truth from Riot's own record (a kill is a headshot when every hit on that victim that round was one, body when none was): over 92 kills on five recordings, a row was found for 84 and **79 were read right (94%)**; headshots score 0.55-0.92, body kills 0.03-0.40. About 0.7 s a kill. | **The kill's row is found by position, not tracked**: the feed adds rows at the bottom, so a moment after a kill its row is the lowest of the player's own -- or one up per later kill. Tracking rows frame to frame swapped two kills a second apart, the case that matters. The feed reader's two-tone test lost the row on a reddish wall and under the network overlay, so the yellow border lines are a second way in. **The "OCR near each kill" half of the ask was measured first and not built for Valorant**: against the record on two recordings, the screen reader already separates close kills (6 of 6 under 2.5 s apart, two of them 0.4 s apart), and OCR reads Valorant's feed in 13-16% of frames. CS2's equivalent needs its own measurement against demos. |
| 2026-10-10 | **AMD and Intel cards do the clip work, not the CPU**, v1.50.0 | Decode goes through D3D11VA (every vendor's Windows decoder) when there is no CUDA, and encode through AMF on a Radeon or Quick Sync on Intel when there is no NVENC; each probed by a real run, as CUDA and NVENC already were. Settings > Encoder offers AMD and Intel. Measured on this machine, a minute of 1080p60 scanned at 10 fps: CPU decode **34.0 s of CPU** in 4.1 s, D3D11VA 5.2 s, D3D11VA keeping frames on the card until the fps filter has dropped them 3.6 s -- and those frames are **byte-identical to the CUDA path's**, so every detector baseline measured on NVIDIA holds. A 15 s clip encode: libx264 14.3 s of CPU, AMF 4.5 s (on this machine's iGPU). The diagnostic now says which decoder and encoder a run used. | **The friend's 20-minute run was CPU end to end**: 9 1/4 minutes of libx264 and 10 1/2 of software decode, with h264_amf and d3d11va in their own ffmpeg the whole time. One trap found by measuring: behind a D3D11VA decode, AMF builds its device from the decoder's, so on a box whose display card is another vendor's it fails outright ("Failed to create derived AMF device") -- the AMF probe now runs behind the same decoder a cut will. And because the AMD encode could not be run on a discrete Radeon here, a hardware encode that fails is retried on the CPU and the CPU is used for the rest of the run: a failure costs speed, never a clip. |
| 2026-10-10 | **Lyrics still off on TISWFLFIL2; the LYRICS stand-in over the video**, v1.49.0 | **v1.48.0's automatic re-timing is taken out -- it made this reel worse.** Measured against the song's own lyric video (Tesseract every 0.2 s, 22 lines): LRCLIB's lines are 0.9 s early on this copy (IQR 0.64-1.06), and the 1.88 s of extra length is digital silence at the *end*, not the front. The vocal-rise score had no peak at 0.9 and picked +1.9, a bar out. In its place a **Timing** control in the Lyrics group (-0.5, -0.1, +0.1, +0.5 s, Reset) moves every line by ear. Words are now sung at a singer's pace -- each word its syllables at what the line's room allows, never slower than 0.32 s a syllable, then the last word held -- and moved onto a vocal rise only within 0.1 s; they used to go on the loudest rises anywhere in the line, which on this mix were the piano and drums ("so", then 1.6 s of nothing). Words on screen while the lyric video shows their line: 52/68 as shipped, 49/66 under v1.48's +1.9, **62/68** with +0.9 and the new pacing. The LYRICS stand-in now shows only while placing ("Move on the picture", a drag, or a move not yet rendered). | **A heuristic that agrees with itself on two songs is not measured.** The length-difference rule was "confirmed" on JVKE and Ambition For Cash by the same vocal-rise score it was meant to check, and both agreed for the wrong reason. The lyric video was the ground truth that existed all along -- many of the player's songs are "(Lyrics)" uploads. Until a real aligner exists, timing is the player's ear, with the 0.1 s step they can hear. |
| 2026-10-10 | **Lyrics two seconds early on the user's TISWFLFIL2 reel**, v1.48.0 | `lyrics.align()` moves a synced lyric onto the recording actually in use before a word is placed. LRCLIB's lyric for JVKE's song was timed on the 120 s release; the user's file is a 121.88 s "(Lyrics)" upload, and every word showed 1.9 s before it was sung. Checked against that upload's own on-screen lyrics, frame by frame: before, the reel was a line ahead ("make" over "so this is love"); after, each word sits on its line. Ambition For Cash was 0.42 s early too and is corrected the same way. The page's note says how far the lines moved. | **Matching a lyric by title and length within 3 s is not matching the recording.** The length difference turned out to be the offset -- the extra is at the front -- so it says where to look, and the vocal band says whether to move. Only shifts near 0 or near that difference are considered, because a dense rap verse rises everywhere (Ambition For Cash scored almost as well 2.8 s the wrong way). Lyrics cached before the record length was kept are fetched once more to learn it. |
| 2026-10-10 | **U6** the lyrics go wherever the player puts them, v1.48.0 | A **LYRICS** stand-in on the Studio's picture, dragged to place, and nine quick places in the Lyrics group, with "Back to the look's place". Stored as `lyrics.pos`, the centre of the line as shares of the frame, clamped 5% from every edge; unset is the look's own place (29% down a vertical frame, 40% down a landscape one). Every look draws there; Caption, which alternates sides by default, centres on it. Rendered on the user's own reel at 30% across, 78% down. | **A centre near an edge pushes a long line off it** -- the first placed render lost the "a" of "addiction". libass cannot be asked a line's width, so each look estimates it from the character count and moves the centre in just far enough; tested with a line placed 5% across in all five looks. |
| 2026-10-10 | **U5** every reel in the Studio, v1.47.0 | "Your reels" lists all of them: two rows folded with **Show all N reels**, a search over name, style, song and "lyrics", a Vertical/Landscape filter with counts, and four orders (newest, oldest, name, longest). Each card is a still of the reel's first kill (intro + the opener's run-up, so not the black first frame), with its shape and length on it; pressing the still plays the reel. Browser test `test_every_reel_is_reachable_not_only_the_newest_ten` on twelve seeded reels. | **The cap was `reels.slice(0, 10)` in the page, with no way past it** -- an eleventh reel's timeline was unreachable except by remaking it. The tools are static markup and only the grid is redrawn, so the search keeps focus while typing; the fold applies only when nothing narrows the list, because a search is already the answer to "which reel". |
| 2026-10-10 | **Studio: first kill off its beat, a double kill cut short** (the user's `ambiforcashlyrics` reel), v1.46.0 | Re-planned from the same clips, song and part: the opener's kill now lands on the hit at bar 2's downbeat (13.68 s) with no slow-motion, where it had taken an off-beat hit at 14.28 s and slowed the run-up to 0.85x to reach it; and its second kill, 0.84 s after the first, is kept (0 of 23 shots now cut before one of their own kills, against 2). Two tests, both failing on the old code. | **Strict "at or after" against a beat-length run-up is a coin toss**: the bass peak on a beat sits a few ms either side of it, so a quarter step of slack goes on the first hit. And `apply_marks` sized each run-up from the gap alone, never asking what the shot before it still had to show. |
| 2026-10-10 | **U4** the tempo finder stops counting hi-hats as the beat, v1.46.0 | Three changes in `beatsync.estimate_bpm`, each measured with a scratch harness (14 songs on disk with published tempos, and 96 synthetic kick/snare/hat patterns at 72-174 BPM): the first lag is searched **inside** 70-180 BPM only -- the extra frame `search_lags` adds for the parabola was winning the search, and a 100 BPM song's eighth-note hats (198.8 BPM) beat the beat and were clamped to 180; halving never drops below 180 BPM's lag; the lag is chosen by its autocorrelation at 1x, 2x and 4x (beat, half bar, bar); and `sharpen` weights each onset by its strength, because equal-weighted off-beat hats cancelled the kicks and pulled 99.4 to 96.8. Synthetic **44 -> 68 of 96**; real songs **13/14 before and after, every tempo within 0.1 BPM**. 8 new tests in `test_beatsync_tempo.py`, 7 of which fail on the old code. | **"Trust the bass when the two disagree", the study's core fix, was measured and rejected**: a bass-only tempo got 10 of 14 real songs (Godzilla, Thunderstruck, HIGHEST IN THE ROOM and Superhero went wrong) where the full envelope gets 13. Weighting the spectrum towards the kick was neutral on real songs too. The 0.30 s run-up was not changed: the studio's run-up is a per-style share of the shot, not the 0.45 s constant the study compared against, and needs its own measurement. MONTERO (179 BPM) is still wrong, now 134 instead of 72. |
| 2026-10-10 | **U3** lyric reels, v1.46.0 | `clips/lyrics.py` and a **Lyrics** group in the Studio's reel inspector: a look (Stamp, Glow, Serif, Caption, Scrawl), a typeface (the look's own or any of nine bundled OFL fonts) and "Star out swear words". At render the song's synced lyrics come from a `.lrc` beside the song, else a cache, else LRCLIB (matched by artist/title and the file's length within 3 s); each word goes on a vocal onset (300-3400 Hz flux); the word sung at a kill turns red, moving off "the"/"a" to the nearest word with weight within 0.5 s; Stamp greys the picture under it. Drawn by libass in the join pass, above the grade and below the mark. A song with no lyrics, no network or an ffmpeg without libass leaves the reel unchanged and says why in the group. Rendered the user's AMBITIONFORCASH reel through the real `StudioJob`: 10 lines, 14 of 18 kills under a red word. | **The samples were placeholder words and the user read them as another song's lyrics** -- the sample page has to show the real thing for its feedback to mean anything. Lyrics are a project setting, not a style, so they survive a restyle and a rebuild. They only cover the reel itself, not an intro clip joined in front. Open: whether a clean-lyrics default suits a public build, and mid-height vs top-band placement (the looks sit at 29% of a vertical frame, 40% of a landscape one). |
| 2026-10-10 | **U2b** pick the matches in a downloaded stream, v1.45.1 | Every saved VALORANT match now has a tick box, "This match is in the video"; when nothing lines up by time the list opens on all of them. The run finds each ticked match in the video by its kill pattern alone (`valorant_match.align_free`), then clips only from where they were found. A ticked match that cannot be found is named on the page and left out. | **v1.45.0 only offered matches it had placed by the clock**, and a stream downloaded from YouTube carries the download's time -- so the user's main case got an empty list. The user's tick replaces the clock; the kill fingerprint, already trusted for CS2 replays, does the placing. Tested: a match 900 s into a video found to within 0.6 s with two stray kills around it. |
| 2026-10-09 | **U2** the saved VALORANT matches, listed -- and chosen, v1.45.0 | The match-record line on Clips gets **Show matches**: every record saved on this PC, newest first, with the map's real name (Riot's `Triad` is Haven), the mode, the result from the player's side (TDM in points to 100, the rest in rounds), the player's K/D/A, and for each match inside the chosen video where it starts. Those carry a **Clip this match** tick box; the run reads only from the first ticked match to the last and drops every kill and round outside them. The list opens by itself when a video holds two or more matches. | On the developer's PC it listed 77 records and put the one competitive match of a 56-minute recording at 8:21, matching Riot's start time. **Untouched, nothing changes**: with every match ticked the run sends no spans and reads the whole video as before, so the feature cannot quietly narrow a run nobody chose to narrow. |
| 2026-10-08 | **U1** the Timeline effects picker, v1.44.0 | Every effect choice on the timeline -- intro, ending, transition, speed, camera move, colour, a shot's kill and hero effects, the overlays and the pools every shot draws from -- opens one dialog: a search box that takes a name, a code or a word from the description; **Recently used** first; a grid of cards each playing its example, and the one under the pointer large beside them. One choice applies on a click; several are ticked and Done. The inspector shows what is chosen as one line, or as chips each with ×. Browser test `test_the_effect_picker_searches_previews_remembers_and_applies`; the three tests that ticked checkboxes now drive the dialog. | **The picker goes through the old controls' own code path** (`studio_inspectorSet` builds the event the dropdown used to send), so undo and the 'not rendered yet' list name each edit exactly as before -- a rewrite of the edit path was the risk, and there was no need for one. Players live in the dialog, not the inspector, because the inspector rebuilds on every edit. Recents are per browser (localStorage), a convenience and never a record. |
| 2026-10-08 | **Valorant V1 + V2**, v1.43.1 | On the outside user's stream, end to end: before, 59 kills of which 37 real; after, every real kill kept and the 13 watched team-mate kills gone. `killmark.dead()` reads the combat report's two borders at fixed columns (own kills 0.00-0.09, watched 0.14-0.61) before and after the emblem; `menu()` the LOCK IN red. Emblem-stage numbers now go into the clip diagnostic. | **A HUD check that sits where streamers put their camera is not a check.** The card test had been measured on footage with no facecam and was right there; the first stranger with one made it silent. Every pixel test should say where it looks, and the next one should prefer the right half of the screen. Also: the combat report is shown after a trade too, so 'dead' has to be read before the event, not only after. |
| 2026-10-08 | **CS2 card tally: T1, T2, T4 fixed** | Ground truth built for the outside user's match: **21 kills**, read off the card's printed count by eye and equal to the in-game scoreboard. Old code: blue, **0 of 21** -- his result, reproduced; shifting the start 2s turned its answer from pink to yellow (72). New code, end to end through `detect.scan` on the same 54 minutes: **hue 285, 20 of 21, 0 extra**, colour saved. Developer demos unchanged: **45/45, 0 extra**. Colour pick replayed at 20 phase offsets: developer 20/20, outside user 19/20 within 15 degrees. Harness kept: `scripts/cs2_hue_score.py`. Ships in **v1.43.0** with UI #14. | **The kill reader was never the problem on his HUD -- the colour was.** At the right colour every one of his 21 kills flashed and 20 were counted. Three things the old colour check could not tell from a tally, each found by measurement: the **main menu** (an agent's boots read as one steady card, and gave red more readings than the real colour on the developer's own 2h36m), **a team-mate's tally while spectating** (real, steady, in the team-mate's colour), and **noise from too few samples** on a HUD readable 4% of the time. Also measured and rejected: lowering `SAT_MIN` to 0.12 (no better), and lowering `EMBLEM_RISE` to catch his gold badge's weak whitening (adds 1-4 false kills on the developer demos; the count path already recovers them). |
| 2026-10-06 | **UI #14** one breakpoint scale | Four media-query pairs (720, 760, 900 ×2, 980) had a `max-width:N` and a `min-width:N` that **both** apply at exactly N, so the page had no answer at its own boundary and file order picked one. All are now `max-width: N-1`; the scale is written beside the rules. 620/880/1100 deliberately left off it (each within 20px of a scale point) and named as debt. `tests/test_breakpoints.py`, 8 tests, proved against a planted regression. On `feat-ui-standalone`, unreleased. | **#15 was measured instead of done, and dropped** — see the Standalone section. A review's numbers are a claim about the build it looked at; measure before restructuring. |
| 2026-10-06 | **v1.42.0** released | Developer Mode (off by default) and the **clip diagnostic**: one JSON per run with stages and timings, every process through `tools.py` with exit code and stderr tail, errors with tracebacks, system and GPU info, home paths redacted. The marker walks a **batch** of clips with an index, can cut a piece out and save it, and can run kill detection on all of them. The slow CS2 HUD reader (feed + scoreboard, 1.19–1.46x real time) is **developer-mode only**, refused server-side without it, and skipped by the release gate — tier 4 had been 93% that one test, 34 minutes. Window guard so test runs stop popping AutoStream on screen. | The general rule went into CLAUDE.md: **a reader slower than ~5x real time is a developer tool**. The diagnostic's first real use (the CS2 row above) showed its gap: modules that pipe ffmpeg themselves are invisible to it. |
| 2026-10-05 | **C2** the whole Counter-Strike match as one video | `clips/match_summary.py`: which seconds to keep, where each round lands in the finished video, and what every chapter is called. Rounds that nearly touch become one span — a hard cut per round in a match that ran continuously is twenty-four joins where the footage already was. Off by default on the Clips page, beside the clips rather than instead of them. | **Counter-Strike before Valorant because of ground truth**: `rounds.from_demo()` gives exact starts, ends, scores and labels out of the `.dem`, so every span is arithmetic over known numbers and 28 tests prove it **without a frame of footage**. The cut itself deliberately adds no new way to touch ffmpeg — it is `master_segments`, which the Rivals summary already proves against real files. One finding: a round that starts and ends in the same second is a *misread digit*, not a round, and padding it gave an eleven-second span and a chapter for something that never happened. |
| 2026-10-05 | **The sweep floor**, 117 → 122 | Three new states put the Studio's kill marker in front of the sweep, and the facecam behind a reel. Declared controls went 190 → 195 as this session added some. | **Five controls were unreachable because of a product gap, not a test one.** The marker was gated on `imported` until S2, so for a seeded run the dialog could not be opened at all and its controls were outside the sweep *however the states were written*. That is what a coverage number is for. Also: the first attempt at those states guessed the library's shape (`games[].clips[]` rather than `games[].folders[].clips[]`) and silently opened nothing — a state that reaches nothing looks exactly like a state that found nothing, so the shape now lives in one injected helper with the reason beside it. |
| 2026-10-05 | **UI #2**, the `--on-media` token pair — **and a test that was green and wrong** | Eight different black-scrim alphas were in use for one job: text drawn over a video frame. Measured against the worst case (a white frame), white text scores `.35 → 2.43`, `.55 → 4.74`, `.62 → 6.19` — so `.54` is the AA floor for normal text. The lightest in use was behind **13px white text on the editor's frame handle at 2.43:1**. Now `--on-media` + `--on-media-scrim` (6.19:1) + `--on-media-scrim-soft` (4.74:1), with the numbers in the stylesheet beside them. | **The browser test for UI #1 could never have failed.** It compared the colour against the literal string `#fff`, and CSSOM normalises that to `rgb(255, 255, 255)` — so it matched nothing, passed from the day it was written, and a fifth offending rule (`.clip-fx-aim.is-on`) shipped underneath it and was found **by eye**. The anti-vacuity guard it carried asked whether the stylesheet was being *read*, which it was; the comparison was the broken part. The real guard now scans the stylesheet's own text in the unit tier, where `#fff` is `#fff` — and **both of its checks are proved against a planted regression**, which is the only way to know a guard works. |
| 2026-10-05 | **C5** chapters, for the montage | A montage is the one output of this app with no way into the middle of it: forty clips joined into eight minutes, and the good one is somewhere in there. `montage.chapter_marks()` computes the offsets with the **same recurrence `_plan_offsets` hands ffmpeg to place the crossfades**, so a chapter lands on the frame its clip starts on. YouTube's three rules are enforced rather than hoped for — first at 0:00, at least three, at least ten seconds apart — because breaking one shows **none** of them with no error anywhere. Chapters closer than the minimum are *dropped, never moved*: a chapter moved to satisfy a rule points at the wrong moment. Offered on the results row, not left in a .txt beside the file. | **Chapters in the live VOD's description were deliberately not built, and that is the finding.** They need kill times mapped from recording-offset to VOD-offset via `_rec_began` against the broadcast's actual start — and when OBS was *already* recording and the session adopted that output, the recording predates the broadcast by an unknown amount. The adopted case is detectable (`state.recording_adopted`), but the arithmetic cannot be verified without a real stream, and wrong chapters on a published VOD are worse than none. The montage's offsets are arithmetic over known durations, so they are provable offline — which is why that half shipped and the other did not. |
| 2026-10-05 | **Five dead settings**, found while starting C5 | Each was on the Settings page with help text promising a behaviour, had a default, and was read by **nothing**. `record.auto_scan` ("find kills after each stream", on by default) was one assignment nothing read — now `clips/prescan.py`, which reads a finished recording on its own thread, cuts nothing, skips what has already been read, and waits for any clip run the user started. `logging.keep_days` — `backupCount` was hard-coded to 7. `ui.open_window` — `MainWindow.run()` has taken a `hidden` argument the whole time and was never given one. `title.fallback_game` — a game the index could not name went out with an empty `{game}`. `record.warn_free_gb` — the only disk signal was the floor at which the recording is *already* being stopped. | **A setting that is on by default and does nothing is worse than one that is missing** — it is a promise in the product's own voice. None of this was findable by a failing test: the schema test checks a key has a default and the defaults test checks a default has a key, and all five passed both. `tests/test_dead_settings.py` now fails the build for any key that exists only in the schema and the defaults. Found by looking for what C5 depended on, not by looking for bugs. |
| 2026-10-05 | **C6** clip ranking | Ranking was kills, then *when it happened* — so every three-kill clip tied and the order inside a tie was the order of the recording, which is not an order of quality. Density (kills per second of the clip as cut) now breaks that tie, with the detector's own confidence after it. The best five are flagged `top` and marked **Best** in the results. Paired UI #12: the folded summary said `2+ kills · 30s clips · vertical too · joined into one` — four settings in form order — and now says what the run produces, leading with a clip count wherever the recording has already been read. | **The kill count had to stay the dominant term.** A four-kill clip ranking under a three would read as a bug whatever the justification, so density is a tie-break and not a weight. And a shortlist is a **flag, not a filter** — nothing is hidden, the other thirty-five are still cut and numbered. Two guards earned their keep: `combine()` and `merge_marks()` each took two lists carrying their own five and would have produced a "best ten"; and `test_local_clip`'s audit caught the new field being read off a selection that a picked file does not supply. |
| 2026-10-05 | **B3, B4, B5** setup that does the work instead of describing it | B3: AutoStream writes OBS's websocket config itself — the step people stop at was six instructions about a dialog in another application, ending in copying a generated password by hand. B5: a 1-unit `liveBroadcasts.list` right after sign-in, so a channel without live streaming enabled is found during setup rather than at the first session. B4: the Google sign-in's age is recorded and days 5–7 get a warning, with publication **inferred** from a token that survives to day 9. | **Two of the three could not be built as written, and saying so was the work.** B4 wanted setup to refuse while the OAuth app is in Testing; Google exposes no publishing status to a client, so that is not buildable — but the fact that matters (a published app's refresh token never expires) is observable, which turns an impossible check into an inference that settles itself. B6 was already done and the roadmap was stale. B2 needs a purchased certificate and is blocked, not pending. |
| 2026-10-05 | **A4** generic highlight detection | A `loudness` profile mode and an `any-game` built-in that needs no calibration at all: it reads the audio against a **rolling median baseline**, so the test is "loud relative to the minute around it" rather than a fixed dBFS that finds everything in one recording and nothing in the next. Measured at ~3,200x real time (it decodes no video), making it the fastest reader in the package by two orders of magnitude. The page stops saying "kills" for it, because it cannot know that. | **The four signals in the original plan are not equal.** Input burst needs a hook at record time and scoreboard delta needs per-game calibration — which is the thing this feature exists to avoid. Audio alone, with the baseline rolling, carries the whole feature. What it buys is a shortlist, not a kill list: it cannot tell a kill from a death, and the honest framing is what makes it usable rather than untrustworthy. The paired UI item (#3, the Clips stepper tick) was already fixed and already has a browser test. |
| 2026-10-05 | **A3** instant replay | OBS's replay buffer, started and stopped with the recording, with its length pushed from config every session. A global hotkey (`ctrl+alt+shift+r`), bound whether or not the feature is on so that switching it on in Settings works without a restart. A dashboard card that reports **what OBS is doing**, not what the config says. Paired UI: the metric strip lays out the cells it is given rather than a hard `repeat(3)` (#7), and no accent fill is painted with hard white any more (#1). | **The clip already exists when the key is pressed**, which makes this the only clip feature that works in a game with no detector — it is the cheapest route to "any game" and it landed before A4, which is the expensive one. Two things worth remembering: OBS answers the save request *before* it has finished muxing, so asking for the filename immediately returns the PREVIOUS replay — a real path to the wrong clip, which is worse than an error; and `#fff` on `var(--accent)` fails WCAG AA in four of the five themes (carbon measures **1.23:1**), so "white on a coloured fill" is never safe while the accent is a user setting. |
| 2026-10-05 | **A2 + B1** clips-only install, and a wizard shaped by the platform | The first run offers the clipper first and marks it Recommended. The step list is built from the chosen platform rather than being a fixed nine, so Twitch and Kick skip Google Cloud, the Google sign-in, the YouTube-only stream settings and the permanent-stream creation — eight steps instead of ten, none of them about a service you are not using. A sign-in step that will not let you past until the platform can actually stream, and a Twitch key that can simply be pasted. Paired UI: the Google Cloud step is a checklist you can keep your place in (#13), and `setup.py` went from **zero** ARIA attributes to a progressbar that says which step of how many, a heading on every step, focus that follows the step, and live regions on all twelve message slots. | **`is_configured` is the wizard's on/off switch, and it is easy to turn off by accident.** Answering "yes, configured" for anything that was not YouTube skipped not the Google steps but the whole wizard — a fresh Twitch install opened on a dashboard with no OBS, no apps and no stream key. It now asks the platform. Also: `ready()` and `configured()` are different questions. Twitch's `ready()` asked `configured()`, which wants a client id and secret that exist only for setting the title — so a first run where a valid stream key had just been pasted left Continue grey. |
| 2026-10-04 | **A1** Twitch + Kick — sign-in and the UI around it | Kick's token exchange fixed (Cloudflare was banning urllib's User-Agent and answering 403 `error code: 1010`, which reads as an OAuth refusal and is not one). The five YouTube-only settings hidden when the platform is Twitch or Kick, with one line saying why. A platform chooser on the dashboard, saving through the same endpoint as the Settings field. Status reports the platform and asks it for the watch url. Three silent defects fixed: the engine built its platform once and never followed a config change; `_session()` memoised an empty session so the status poll made every "is a stream live" test answer yes forever; `is_configured()` held Twitch users in a Google setup wizard. | **A platform is not shipped when its API client passes tests.** Every one of those three let the config, the page and the stored value all say Twitch while the engine streamed to YouTube — nothing failed, nothing logged. Capability flags are only honest if the UI reads them, so each new platform owes a pass over what the pages still claim. Also: the browser tier could not run while the user's own app was open, which is exactly when a UI fix is being checked — fixed with `AUTOSTREAM_INSTANCE` and `AUTOSTREAM_VERIFY_SOURCE`. |
| 2026-10-04 | *(pre-roadmap)* **v1.40.0** | The Clips page split into six stages; the whole recording plays and a part can be trimmed and saved; the voice pack is installable; the browser test tiers (sweep + journey). Tier 4 green. | Cleared the tree so A1 starts from a clean, released base. Also set the precedent the roadmap assumes: a UI change is not finished until a browser has pressed the button — three bugs in this release passed 2200 unit tests and were caught the moment one did. |

### How to add a row

1. Land the feature, with tests.
2. Set its row in the phase table above to `done` (or `in progress`, with
   what is left).
3. Add a row here. Say what you learned, not only what you built — if the
   estimate was wrong, or the order turned out wrong, say so and change the
   order.
4. If the work changes the version, say which release carries it.
