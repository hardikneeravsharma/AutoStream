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
| A1 | **Twitch + Kick auto go-live** | 24% → 89% of gaming watch time, and *cheaper* than the YouTube path already shipped | not started — **credentials ready** |
| A2 | **Clips-only install path** | Removes the Google account from first run — the hardest step, for a feature most clipper users never want | not started |
| A3 | **Instant-replay hotkey** | The most-used feature in every competitor. Cheap, and it covers every game at once | not started |
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
| B1 | Clips-only is the **default** first run; go-live becomes opt-in | not started |
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

## State of the tree, 2026-10-05

**Read this before assuming the repo is clean.**

- v1.40.0 (the Clips stages batch) is merged and published; the detached-HEAD
  batch described here before is gone.
- **v1.40.1** is the open PR: the NVIDIA checks (`has_cuda`, `has_nvenc`) now
  prove the card works instead of trusting ffmpeg's build list. Without it
  every clip job on an AMD or Intel GPU fails -- the first outside user, on a
  Radeon RX 9070 XT, got "0 samples" from the CS2 tally.
- Tests at the time of writing: **2260 offline**, **154 browser**.

Nothing in Phase A has been started.

---

## Progress

One row per feature as it lands. Newest first. Fill in the date, what shipped,
and — the part that matters to the next session — **what it changed about the
plan**, because a roadmap that never moves was never being followed.

| Date | Item | What landed | What it changed |
|---|---|---|---|
| — | — | *Nothing from this roadmap yet.* | — |

### How to add a row

1. Land the feature, with tests.
2. Set its row in the phase table above to `done` (or `in progress`, with
   what is left).
3. Add a row here. Say what you learned, not only what you built — if the
   estimate was wrong, or the order turned out wrong, say so and change the
   order.
4. If the work changes the version, say which release carries it.
