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

### Phase A — Tier 1, the market unlocks

These change **who can use the product**, not what it does. Nothing in Phase B
matters until these are in.

| # | Feature | Why it is first | Status |
|---|---|---|---|
| A1 | **Twitch + Kick auto go-live** | 24% → 89% of gaming watch time, and *cheaper* than the YouTube path already shipped | **code done** — seam, both platforms, sign-in, UI and the two paired UI items. Twitch verified against the live API; Kick needs `channel:read` re-granted. No real stream pushed yet |
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
| B2 | Code-sign the binary (SmartScreen sits between every download and every install) | **blocked** — needs a purchased certificate (OV ~$200/yr, or an EV token). Nothing to build until one exists |
| B3 | Configure the OBS websocket automatically — read OBS's own config, enable, set port and password | **done** — reads it as before, and now writes it too (only while OBS is shut, because OBS rewrites the file from memory when it quits) |
| B4 | Refuse to finish setup while the OAuth consent screen is in Testing (it expires in ~7 days and looks like the product breaking) | **done, differently** — publishing status is not exposed to the client, so refusing is impossible. Inferred instead: a token still refreshing at day 9 proves the app is published; before that, days 5–7 get a warning |
| B5 | Preflight YouTube live enablement before anything else (a new channel takes 24h; finding out at go-live wastes an evening) | **done** — one quota unit, right after sign-in |
| B6 | Finish setup into a *running* engine (today nothing streams until a manual restart, and no screen says so) | **already done** — `await_setup()` starts the engine in-process. The roadmap entry was stale |

### Phase C — Tier 2, close the visible gaps

| # | Feature | Status |
|---|---|---|
| C1 | Auto-publish with scheduling (TikTok, Reels, Shorts) | not started |
| C2 | Match summaries for CS2 and Valorant — both already have exact ground truth | **Counter-Strike done**; Valorant still to come. The cut rides `master_segments`, already proven by the Rivals summary |
| C3 | Four to six more titles, each shipping with its regression harness | not started |
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

### Deliberately not on the roadmap

- **AI co-host avatar** — Streamlabs, ai_licia and Questie are ahead and
  better funded.
- **Cloud rendering** — contradicts the local-first promise, which is the
  product's main defence.
- **macOS** — no game capture story, and all four supported titles are
  Windows-first.

Do not add these back without a reason that is written down here.

---

## State of the tree, 2026-10-04

- `__version__` is **1.40.0**, merged to `main` as `76d8d43` and published:
  <https://github.com/hardikneeravsharma/AutoStream/releases/tag/v1.40.0>
- The working tree is clean, on a detached HEAD at `76d8d43`.
- Tests at that release: **2253 offline**, **154 in a browser**, and tier 4
  (clip detectors against real-footage baselines) green in 1908s.

A1 is part-built: the platform seam, Twitch, Kick, the OAuth sign-in and the
UI that follows the choice are in and tested. What is NOT proven is a real
go-live on either — no stream has actually been pushed to Twitch or Kick.
That is the next thing to establish, and it needs the user at the keyboard.

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

**#15** lazy-render the Studio panes. **5,348 of the document's 6,325 DOM
nodes** are inside `#view-studio` on every page, including all four panes,
whether Studio is open or not. Worth doing on its own.

**#14** the breakpoint scale — 20 ad-hoc media queries with off-by-one pairs
(719/720, 759/760, 899/900, 1119/1120). Do it *before* adding more, not after.

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
