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

Follow the UI contract below (tokens, focus rings, one JS scope) and ship it
with a browser test — UI #10, the shared player component, pairs naturally
with the previews.

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
| C2 | Match summaries for CS2 and Valorant — both already have exact ground truth | **Counter-Strike done**; Valorant still to come. The cut rides `master_segments`, already proven by the Rivals summary |
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

## State of the tree, 2026-10-08

- `__version__` is **1.42.0**, published and on `main` as `6c90157`:
  <https://github.com/hardikneeravsharma/AutoStream/releases/tag/v1.42.0>
  Phase A, Phase B bar B2, C2/C5/C6, S1/S2 and the UI items in the Progress
  table all ship in it (v1.41.0 carried most of them; v1.42.0 added the clip
  diagnostic and the marker batch).
- **v1.43.0** carries UI #14 and the CS2 card-tally fixes T1, T2 and T4.
- The CS2 card tally is **broken for at least one outside user** -- see
  [Now](#now--the-cs2-card-tally-fails-for-an-outside-user-2026-10-06).
- Earlier, v1.40.1 made the NVIDIA checks (`has_cuda`, `has_nvenc`) prove the
  card works. That fix holds: the friend above is on a Radeon and his decode
  ran in software as intended.

### What is not finished

Written down rather than left looking done:

- **A1 has never gone live.** The seam, both platforms, the OAuth sign-in and
  the UI that follows the choice are in and tested against the live APIs --
  Twitch resolves its channel id and categories. But no stream has been
  pushed to either, and Kick's sign-in came back with three of its four
  scopes, so `channel:read` has to be granted before a Kick session can
  start. That one needs the user at the keyboard.
- **C2 is Counter-Strike only.** Valorant has the match API for it and has
  not been done.
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
