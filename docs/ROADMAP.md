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
| A4 | **Generic highlight detection** | Audio energy, kill-sound onset, input burst, scoreboard delta. Turns "4 games" into "any game" | not started |

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
| B2 | Code-sign the binary (SmartScreen sits between every download and every install) | not started |
| B3 | Configure the OBS websocket automatically — read OBS's own config, enable, set port and password | not started |
| B4 | Refuse to finish setup while the OAuth consent screen is in Testing (it expires in ~7 days and looks like the product breaking) | not started |
| B5 | Preflight YouTube live enablement before anything else (a new channel takes 24h; finding out at go-live wastes an evening) | not started |
| B6 | Finish setup into a *running* engine (today nothing streams until a manual restart, and no screen says so) | not started |

### Phase C — Tier 2, close the visible gaps

| # | Feature | Status |
|---|---|---|
| C1 | Auto-publish with scheduling (TikTok, Reels, Shorts) | not started |
| C2 | Match summaries for CS2 and Valorant — both already have exact ground truth | not started |
| C3 | Four to six more titles, each shipping with its regression harness | not started |
| C4 | Vertical live output | not started |
| C5 | Auto title, description, chapters and thumbnail from the match result | not started |
| C6 | Clip ranking — a ranked shortlist of 5 beats a folder of 40 in filename order | not started |

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

**S1 · Adding clips, plural.** `studio_impAdd` takes one file and stops:
`/api/clips/pick` returns a single `path`, because `clips_pick` calls Tk's
`askopenfilename`. Somebody with a folder of twenty clips does the whole dance
twenty times. The change is `askopenfilenames` behind a `multi` flag, a
response that carries `paths`, and a loop in `studio_impAdd` -- then the
marker opens on the first and moves to the next on Save, so a batch is one
pass rather than twenty.

Keep the single-file answer working: `clips_pick` serves intros, outros and
songs as well, and none of those wants a multi-select.

**S2 · The kill marker should reopen for any clip.** It is gated on
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
