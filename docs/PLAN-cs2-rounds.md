# Plan — round-aware clipping for Counter-Strike 2

**Status: plan only. Nothing here is built.**

## Why the current clipper is wrong for CS2

The clipper finds kills and cuts a window around each burst. That is the right model for Delta
Force, where a respawn shooter has no structure above the kill — a triple is a triple whenever
it happens.

Counter-Strike does not work that way. A round is the unit of drama, and the same three kills
mean completely different things depending on where they land in it. Three kills opening a
round with five teammates alive is a good start. The same three kills alone against three
opponents is the clip people actually watch. The current clipper cannot tell those apart,
because it never looks at anything except the kill feed.

Worse, it systematically *misses* the best rounds. A 1v2 won with a single kill produces one
kill and gets cut as a 4-second single, ranked below every ordinary double. The round that
would have been the highlight of the session is the one the ranking buries.

So CS2 needs a second detector operating a level up: **segment the recording into rounds, read
what happened in each, and clip rounds rather than bursts.**

---

## The signals, measured

All of these were read off the user's own 1920×1080 recording
(`2026-08-20 00-13-08.mp4`). Positions are fractions of the frame; the implementation must
calibrate them per user, because HUD scale is adjustable.

| Signal | Where | Reads as | Confirmed |
|---|---|---|---|
| **Round timer** | x 0.482–0.518, y 0.009–0.039 | `1:14`, `0:07` (red under 10s) | yes |
| **Score** | x 0.477–0.523, y 0.043–0.081 | `12 │ 12`, left and right team | yes |
| **Players alive** | x 0.477–0.523, y 0.083–0.109 | `👤3 │ 👤2` | yes |
| **Player cards** | x 0.24–0.76, y 0.00–0.10 | 5 per side: name, avatar, health, money | yes |
| **Dead marker** | under each card | a skull appears when that player dies | yes |
| **Kill feed** | x 0.60–1.00, y 0.03–0.30 | already read by `clips/killfeed.py` | shipping |

Two things make this much cheaper than the kill feed:

**The digits are in fixed positions and there are only ten of them.** Timer, score and alive
counts should be read by template-matching digit glyphs, not by Tesseract. That is the same
normalised cross-correlation already in `clips/detect.py`, against a 10-glyph alphabet cut
once. It will be roughly two orders of magnitude faster than an OCR pass and considerably more
reliable, because the glyphs are pixel-identical every frame rather than antialiased text over
moving gameplay.

**Nothing here needs to be read every second.** The timer changes once a second but only its
*transitions* matter — round start, round end. Sampling at 1 fps is ample and 0.5 fps is
probably fine, because a round lasts 30–115 seconds.

---

## Foundation: segmenting the recording into rounds

Everything below depends on this, and it has to be solid before any clip type is worth
building.

A round boundary is where **the score changes**. That is the least ambiguous signal available:
it is a discrete step, it says *who won*, and it cannot be confused with anything else on
screen. The timer is a useful cross-check — it resets to 1:55 and counts down — but it also
pauses, goes red, and is replaced by the bomb timer, so it should corroborate rather than
decide.

A round record:

```
round_number      from the score sum, e.g. 12+12 -> round 25
started, ended    seconds into the recording
duration
my_side           which half of the HUD the player's own card sits on
won               did my side's score increment
my_kills          from killfeed.py, between the boundaries
my_deaths
alive_curve       [(t, my_alive, enemy_alive), ...] sampled through the round
i_died_at         from the skull under my own card, or my alive-count dropping
```

**Which side is mine** is settled once per match, not per round: find the player card whose
name matches the configured in-game name. Sides swap at half time, so this must be
re-established when the score resets or the card order changes — a real edge case, not a
theoretical one, and the first thing that will break if ignored.

**Warm-up and match end must be excluded.** Score at 0–0 with the timer behaving oddly, and
long stretches with no score change at all, are not rounds. An 88-minute recording contains
several matches plus menus between them.

---

## The clip types

Ordered by how confidently each can be detected, not by how much the user asked for them.

### 1. Multi-kill round — 4 or 5 kills *(requested #4)*

**Rule:** `my_kills >= 4` between round boundaries.

**Confidence: high.** Kills are already detected and round boundaries are the easy part. The
only failure mode is the known one — an assist whose killer's name is unreadable counting as a
kill — which can inflate a 3k to a 4k. Requiring 4 rather than 3 makes that less likely to
matter.

**Clip window:** first kill minus pre-roll, to round end. A 4k round is worth showing whole.

---

### 2. Fast multi-kill *(requested #1)*

**Rule:** `>= 3` kills inside a rolling window of `<= 5s`. Tunable; 3-in-5 and 4-in-8 are both
worth offering.

**Confidence: high.** This needs no round data at all — it is a tighter version of what the
burst clusterer already does, and could ship before the rest.

**Note:** the kill *timestamps* must be the refined ones. Before the refine pass added
recently, timestamps lagged the real kill by up to 2 seconds, which would make a genuine
3-in-4s look like 3-in-6s and fall out of the window.

---

### 3. Last man standing *(requested #2)*

**Rule:** `my_alive == 1` while I am alive, for at least ~3 seconds.

**Confidence: high.** Read straight off the alive counter. "While I am alive" is the important
qualifier and comes from my own card's dead-skull; without it, the last teammate alive while I
spectate would trigger it.

**Clip window:** from the moment my count reaches 1 (minus pre-roll) to round end.

**This is a *state*, not an outcome** — it fires whether or not I go on to win. That is
deliberate: losing 1v3 having nearly pulled it back is still a highlight. Whether to keep the
losses is a setting.

---

### 4. Clutch, 1vN *(requested #3)*

**Rule:** last man standing **and** `enemy_alive >= 2` at that moment **and** my side wins the
round.

**Confidence: high**, and this is the single most valuable clip type on the list. It is a
strict subset of #3 plus the score check.

**Label it by what it was:** `1v2 CLUTCH`, `1v3 CLUTCH`, taking N as the enemy count at the
moment I became last alive. A 1v4 or 1v5 should rank above everything else the session
produced.

---

### 5. Chaotic round *(requested #6)*

**Rule:** `duration <= ~35s` and at least one kill of mine, regardless of the result.

**Confidence: medium.** The duration is reliable; whether a short round is *interesting* is a
judgement the signal cannot make. A round that ends in 20 seconds because the team got rushed
and folded is chaotic; one that ends in 25 seconds because of a fast bomb plant may not be.

**Suggestion:** rank these below the others and gate them behind a setting, rather than mixing
them into the main output. Better still, add a second condition that separates chaos from a
clean fast round — **total kills across both teams**, not just mine. Six kills in 25 seconds is
chaos. Two is not. The kill feed already shows every player's kills, so this is available
without new detection work, and it is a much better definition of "chaotic" than duration
alone.

---

### 6. Grenade, smoke and blind kills *(requested #5)*

**Rule:** template-match the modifier icons CS2 draws in the kill feed row between the weapon
and the victim.

**Confidence: medium, and this one needs research before it is promised.** The rule is sound —
these icons are fixed glyphs at a predictable place, which is exactly what the existing
template matcher is good at. The uncertainty is in the inventory: CS2 draws separate icons for
headshot, wallbang, no-scope, through-smoke, blinded attacker, and grenade kills use the
grenade as the weapon icon. Several of them are small and some may not appear in this user's
footage at all, so there may be nothing to cut a template from.

**Do this before committing:** sweep the existing recording for feed rows containing the
player's name, crop the region between weapon and victim, and build a contact sheet of what
actually appears. If an icon never occurs in 88 minutes of footage, it cannot be calibrated and
should be dropped from the plan rather than shipped untested.

Grenade kills are the easy subset — the weapon icon *is* the grenade, and it is large.

---

## Types the signals make available that were not asked for

Worth considering because they cost almost nothing once rounds exist:

- **Ace** — 5 kills in a round. Already covered by #1, but deserves its own label and top rank.
- **Flawless round** — my side wins with `my_alive` never dropping below 5. A team highlight
  rather than a personal one.
- **Comeback** — winning a round after being down 1v3 or worse. Overlaps with #4 but is the
  rarer, better version.
- **Opening kill** — first kill of the round, within the first ~15 seconds. Short and very
  postable.
- **Round-loss survival** — I stayed alive to the end and still lost. Often visually dramatic,
  and currently invisible to a kill-based clipper.
- **Match point** — any round where the score means the match ends. Context, not action, but it
  makes a montage's final clip choose itself.

---

## One round, several labels

A single round can be an ace *and* a 1v3 clutch *and* fast. The design must decide this
explicitly or it will emit three overlapping clips of the same 40 seconds.

**Proposal:** a round produces **at most one clip**, carrying every label that matched, ranked
by the strongest. Rank order, highest first:

```
ACE (5k)  >  1vN CLUTCH  >  4 KILLS  >  LAST ALIVE  >  FAST 3K  >  CHAOTIC
```

The caption uses the top label; the manifest records all of them, so the Shorts upload flow can
pick a different one if the top label makes a weaker title.

---

## Where the code goes

| File | Change |
|---|---|
| `autostream/clips/hud.py` | **new** — digit and glyph templates, region calibration, `read_frame()` returning timer/score/alive |
| `autostream/clips/rounds.py` | **new** — segments a recording into `Round` records, merges in kills from `killfeed.py`, evaluates the rules, returns labelled highlights |
| `autostream/clips/plan.py` | a second windowing mode: round-based, alongside the existing burst-based one |
| `autostream/clips/profiles.py` | the CS2 profile gains a `rounds: true` flag and the HUD regions |
| `autostream/clips/jobs.py` | the scan step reads the HUD in the same pass as the feed, so the recording is decoded once |
| `autostream/ui/clips.py` | per-type checkboxes, since not everyone wants chaotic rounds |
| `tests/test_rounds.py` | **new** |

**Read the HUD in the same decode pass as the kill feed.** Both need the same frames at the
same rate. Two separate passes would double a 15-minute scan for no reason. This means
`_extract` should crop *two* regions per frame, or one taller region covering both.

---

## Cost

The HUD read is close to free next to what already runs: digit template matching over three
small regions, against a full OCR pass over the feed. If it shares the existing decode, the
added time should be **under a minute** on an 88-minute recording. This should be measured
early — if it is not near-free, the design is wrong.

Round segmentation itself is arithmetic over a list of samples. No cost.

---

## Verification

The pattern that has worked on this codebase, and the one that caught every bug in the kill
detector, is: **measure, then check by eye against the footage, then pin the measurement in a
test.**

1. **Round boundaries first, and alone.** Segment the 88-minute recording and print every round
   with its number, duration, score and result. Check a dozen against the video by hand. If
   boundaries are wrong, everything downstream is wrong and no clip rule can be trusted.
   Warm-up and between-match gaps are where this will fail.
2. **Alive counts against the feed.** The alive counter and the kill feed are independent
   readings of the same events — every kill in the feed should correspond to a drop in one
   side's count. Cross-checking them is a free, powerful consistency test, and disagreement
   localises the bug immediately.
3. **Each clip rule, against hand-labelled rounds.** Watch enough of the recording to label
   every clutch and 4k+ by hand, then measure the rule against that list. Report false
   positives *and* false negatives.
4. **A ground-truth set spanning the whole recording, not one window.** This is the specific
   lesson from the kill detector: the 12-minute window used to tune `MAX_GAP` and `X_TOL`
   turned out to be completely insensitive to both, and two real bugs lived outside it. Sample
   rounds from across all 88 minutes.

---

## Risks, honestly

- **HUD scale and resolution.** Every region here is measured from one user's 1080p recording
  with their HUD settings. Someone else's will differ. Regions must be calibrated, not
  hard-coded — the same mistake `ref_height` exists to prevent for templates.
- **Half-time side swap.** Sides change, and the player's card moves. Getting this wrong
  inverts every win/loss and turns clutches into losses. It will not show up in a short test
  window.
- **Overtime and non-standard modes.** Score logic assuming first-to-13 breaks in overtime and
  in casual. Segmenting on score *change* rather than score *value* avoids most of this, which
  is a further reason to prefer it.
- **Spectating after death.** After I die the HUD still shows the round, and the feed still
  shows kills — none of them mine. Every rule must be conditioned on my own alive state, or
  teammates' kills will be attributed to me.
- **The existing assist limitation carries over.** An assist whose killer's name is unreadable
  counts as a kill, so a 3k can present as a 4k. Round-level rules inherit this and should not
  claim more precision than the kill detector has.

---

## Out of scope

- Reading the bomb timer or plant/defuse state
- Economy (money is legible, but buy rounds are not highlights)
- Weapon identification beyond the modifier icons in #6
- Applying any of this to Delta Force or Valorant — the HUD is entirely different
- Automatic uploading, which is `PLAN-shorts-upload.md`

---

## Decisions needed before building

1. **Round clips are long.** A round runs 30–115 seconds, but the short-form preset caps clips
   at 15. Should a round clip be the whole round (good to watch back, too long for Shorts), or
   trimmed to the action (postable, loses the build-up)? My suggestion: cut **both** from one
   round — the full round into `rounds/`, and a trimmed vertical into `vertical/` — since the
   expensive part is the seek, not the encode.
2. **Do losses count?** A 1v3 lost at the last moment is often better viewing than a 1v2 won.
   Default to including them, with a setting to exclude.
3. **How many clips per session is useful?** 88 minutes is roughly 60–90 rounds. If 20% qualify
   that is 15–18 clips, which seems right, but the thresholds should be tuned against what
   actually comes out rather than guessed here.
4. **Build order.** Fast multi-kill (#2) needs no round data and could ship first as a quick
   win. Everything else should wait until round segmentation is verified, because it is the
   foundation and a wrong boundary silently corrupts every rule above it.
