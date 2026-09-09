# Detector work — where things stand

A running record of what has been built, what was measured to get there, and
what is coming next. Written so the next session can pick up without re-deriving
anything, and so the numbers are recoverable rather than remembered.

Everything below was measured against real footage, named in each section.
Nothing here is a projection.

---

## Summary

| Game | How kills are found | Needs | Speed | Verified |
|---|---|---|---|---|
| Delta Force | HUD glyph, template matched | nothing | ~60s per 2h | 219 kills, one session |
| Valorant | feed bars, no OCR | **nothing** | 20x real time | **23/23 kills, by eye** |
| CS2 | kill tally cards, no OCR | nothing (HUD colour is measured) | 13x real time | partly — see below |
| CS2 + demo | `.dem` from Valve | the demo | 1.6s to parse | **12/12 kills, 16/16 rounds** |

375 tests pass.

---

## Valorant — feed bar detector (`clips/valorant_feed.py`)

**Shipped and verified.** Measured on `2026-08-22 13-06-33.mp4` (1920x1080, 45.9 min).

OCR was tried first and abandoned on evidence: Tesseract reads the player's own
name in **13-16% of the frames its row is on screen**, and six preprocessing
variants over 176 frames scored between 1% and 16%. A detector resting on that
would miss most kills silently.

What the game actually draws is a **yellow border around the local player's own
half of a feed row**. Which end it is on is the whole answer.

Measured colours, from frames verified by eye:

```
red     R 208  G 106  B  92     the enemy team's half
green   R 118  G 186  B 160     your team's half   (a TEAL -- B is 160)
yellow  R 220  G 210  B 125     the border round YOUR segment

G - R        green +68   red -102              separates the teams
min(R,G)-B   yellow +85  red +14   green -42   separates yours from theirs
```

Result: **23 kill events, all 23 checked against the footage, all 23 real.**
Recall: 385 of 397 yellow-bearing sightings covered; no missed moment has more
than two frames of evidence.

Bugs found by measuring, each now a test:

- `G - max(R,B)` scores the teal green at 26 and loses whole rows. `G - R` works.
- Sky blue passes a naive green test, so the agent-select screen read as five
  rows a frame. `b <= g` fixes it — the ally colour is a teal, sky is not.
- Brick walls read as red and sky as green, so a single colour finds hundreds of
  rows in scenery: an unfiltered pass returned **347 kills and 497 deaths**.
  Requiring *both* team colours rejected all 25 known false positives.
- A whole-screen flash turned three rows into deaths at once. Caught by a game
  rule, not a threshold: you die at most once a round.
- Rows slide in over a second and their geometry is nonsense while they do.
  Three false kills were animation frames; rejected by requiring the row to have
  background to its right.
- An assist puts your portrait on someone else's row, 130px clear of the bar,
  where your own kill portrait touches it. Adjacency separates them; distance
  from the row edge does not (14px apart).
- `refine()` was added after the player reported clips starting *after* the
  first kill: detection lagged the real row by **1.8-2.9s**, because the
  slide-in frames are deliberately discarded. Only the first kill of a burst is
  refined — refining both collapsed the burst span and made a "2 kills" clip
  show one.

## CS2 — kill tally detector (`clips/cs2_cards.py`)

**Built and unit-tested; the full-recording count is NOT audited.**
Measured on `2026-08-22 21-05-41.mp4`.

CS2 draws your kills for the current round as a fan of cards above the rank
emblem. It resets each round and is absent at zero.

```
1 card  width 34 px        width = 18 + 16 x kills, exactly
2 cards width 50 px        every sample of a count measured the same width
3 cards width 66 px
```

A kill also makes the tally **flash** — 250 -> 1748 mask pixels for ~0.9s. So
the flash says *when* and the settled width says *how many*, and they check each
other.

Why this beats reading the feed: no OCR, **no Tesseract**, no in-game name, and
assists cannot leak in because the tally is only ever your own kills.

Measured pitfalls:

- Width during a flash is meaningless — one kill measured 76px, wider than a
  real three. Flash frames are discarded and a count must repeat before it is
  believed.
- A hue *projection* cannot separate magenta from Anubis sandstone (35-44 vs a
  real card's 46-68); one scan reported four kills in a single frame. Hue
  *distance* separates them.
- Width was hue-sensitive (34px at hue 338, 48px at 348) until columns were
  required to have 5 stacked pixels. Then 34/50/66 at every hue from 330 to 348.
- While dead you watch a team-mate and the tally shows *their* kills. Detected
  from the spectator panel's text edges: 7.8-15.3 spectating vs 0.9-3.3 alive.
- Deaths come free from that same panel, debounced — undebounced it reported
  **73 deaths in a match of about 25 rounds**.

**Known gap:** the full scan reports 17 kills over 45.6 min, and the demo says
the true figure for the match inside it is 12 plus a second match. Against the
demo it scored **11 of 12, one missed, two invented**. That audit has not been
turned into fixes yet.

## CS2 — demo parsing and VOD sync (`clips/cs2_demo.py`)

**Built and verified end to end** on `de_anubis`, synced to
`2026-08-22 21-05-41.mp4`.

Uses `demoparser2` (pip). Note the blueprint's `cski` / `github.com/krodar/cski`
**does not exist**.

```
demo   : de_anubis, 16 rounds, 115 kills      parsed in 1.1s
player : YUVANETA                             worked out, not configured
sync   : offset +166.60s  rate 1.000029       11 of 12 kills aligned, worst error 1.16s
labels : 12 kills, 8 deaths, 9 headshots, 1 through smoke
```

Three things worth keeping:

- **It picks the demo itself.** The map comes from the header without parsing,
  so scanning the whole replays folder is cheap — it chose the right one of four
  in 5.6s.
- **It works out who you are.** The pixel detectors only ever report the local
  player's kills, so the demo player whose kill pattern aligns is you. No
  in-game name on this path either.
- **The sync is a fingerprint, not an anchor.** Every demo-kill/detected-kill
  difference is a candidate offset and the best wins. It survived the detector
  missing one kill, inventing two, and finding four more from a *second match*
  later in the same recording. A **rate** is searched alongside the offset, so
  128-tick demos work; a least-squares fit afterwards only polishes drift. If
  fewer than 60% of demo kills line up, it **refuses** — a wrong offset does not
  fail loudly, it mis-cuts every clip in the match.

Clips re-cut from demo timings, against the pixel scan:

| | pixel scan | demo timings |
|---|---|---|
| Coverage | 91% | **100%** |
| Time | 288s (220s scanning) | **64s**, no scan at all |
| False positives | 2 | **0** |
| Missed | 1 | **0** |

Verified by eye: the clip named `3kills` contains exactly three.

## Per-game requirements (`clips/profiles.py`)

Profiles now **declare** what they need, checked before a scan rather than
failing minutes in. `auto` requirements are measured off the user's own
recording and never asked for.

```
Delta Force   []                     template ships
Valorant      []                     finds you by colour
CS2 cardcount [hud_hue]  auto=True   measured, then cached to the profile
CS2 killfeed  [player]   auto=False  blocks, and says where to set it
```

Two bugs fixed on the way: killfeed calibration **proved** the in-game name
against real frames and then discarded it, and `why_not()` pointed at the
Library page, which has no name field — so Valorant, arriving as a shortcut,
could never be given one at all.

---

## Done since — the round layer, the voice, the arc

All three were built against the same match: `2026-08-22 21-05-41.mp4`, the
`de_anubis` demo beside it, and the twelve kills the card detector had already
found.

### 1. The CS2 round layer now comes from the demo (`rounds.from_demo`)

`rounds.py` still has its pixel path, and it is still the only option for a game
that gives you nothing else. Counter-Strike gives you a demo, so the same
`Round` objects are built from Valve's record instead, and the detector is
demoted to a fingerprint that locates the demo inside the recording.

```
demo     de_anubis, 16 rounds, 115 kills           parsed in 1.6s
sync     offset +166.60s  rate 1.000028            12 of 12 kills, worst error 0.01s
rosters  read at each round's freeze end           CT r1-12, T r13-16
record   13-3, match point announced in round 16
mine     12 kills, 8 deaths, 9 headshots, 1 through smoke
```

What changed beyond "the numbers are exact":

- **`parse_ticks` at the freeze end is the whole answer to the half-time swap.**
  It is the one tick in a round where everybody is alive and on their final
  side, and reading it per round makes a swap simply the next round's answer.
  On the pixel path the swap is a function that looks for a reversed score
  through a misread. Round 13 proves the difference: the player got no kills and
  no deaths in it, so a roster derived from the kill feed alone says nothing at
  all, and `parse_ticks` says T.
- **Warm-up kills had to be dropped.** They arrive with the same shape as real
  ones. `is_warmup_period` was present on all 116 rows and true on none in this
  match, but a demo of a game joined late will have them, and they would inflate
  the total the sync divides by.
- **Round numbering is 1-indexed off the demo's own columns.** `round_start` and
  `round_end` carry `round`; `round_freeze_end` carries `total_rounds_played`,
  which is one behind. Pairing freeze-end to rounds by POSITION rather than by
  number would shift every round's opening moment by one on a truncated demo.
- **Rounds open at the freeze end, not at `round_start`.** The twenty seconds
  between them is the buy menu.
- **A finding that only exact alive counts could produce.** Round 8 came out
  labelled `ALMOST 1v4` — a round in which the player did nothing and then died.
  The pixel path could never surface it, because it needed kills to infer the
  counts in the first place. A lost last stand now needs a kill in it.
- **New labels, all of them demo-only:** `THROUGH SMOKE`, `WALLBANG`,
  `NO SCOPE`, `KNIFE KILL`, `ZEUS`, `NADE KILL`, `BLIND KILL`,
  `STREAK BREAKER`, `MATCH POINT`, `PISTOL ROUND`. Labelled because they are
  rare, measured over the whole match: 4 smoke kills and 2 wallbangs in 115,
  against **48 headshots** — which is why a headshot is not a label.
- **`cs2_demo.audit()`** marks the detector against the demo, counting only
  kills inside the demo's own span. A recording routinely holds a second match
  the demo knows nothing about, and calling those false positives marks the
  detector down for being right.

### 2. Spoken hooks (`clips/voice.py`)

Kokoro-82M as ONNX, on the CPU. The PyTorch `kokoro` package pulls a
multi-gigabyte torch install; `kokoro-onnx` plus a 177 MB fp16 model file is a
download the user opts into once, and `paths.MODELS_DIR` keeps it outside
`ROOT` so a rebuild does not delete it.

```
load     0.98s        fp16, onnxruntime, CPU
synth    1.36s        for 1.17s of speech -- roughly real time
voices   54
mix      game audio ducked under the voice by sidechaincompress
```

A clip with nothing worth saying stays **silent**, because "check this out" over
an ordinary double kill is worse than nothing.

**The first version read the label aloud, and that was the wrong idea.** It said
"Anubis. One versus two." over a clutch — a caption with a full stop in it,
stating what the clip contains to someone about to watch it contain that. The
label now chooses a POOL and the clip chooses a line out of it, in the voice of
the channel's own shorts titles:

```
CLUTCH 1vN      "they had the numbers. I had the timing."
                "they thought the round was free."
THROUGH SMOKE   "couldn't see a thing. didn't need to."
ALMOST 1vN      "one more bullet and this is a highlight."
STREAK BREAKER  "this is where it finally turned."
```

Which line comes from where the clip sits in the recording, so a rerun says the
same thing and two clutches in one session do not. What has already been said is
passed in and wins over that.

Four things were wrong first and are now tests:

- Labels were `upper()`ed before matching, so `1v3` became `1V3`, every pattern
  containing a `v` fell through, and a 1v3 clutch announced itself as
  "Triple kill."
- `sidechaincompress` ends with its **shorter** input, so an unpadded
  two-second hook cut a fifteen-second clip down to two seconds of video — and
  produced a perfectly valid file while doing it. `apad` on the sidechain fixes
  it; measured before and after: 15.0s in, 15.0s out.
- A line beginning with a spelled-out number starts lowercase, and Kokoro reads
  case as prosody, so "three kills in five seconds." was delivered as the middle
  of a sentence nobody said. Capitalising only the FIRST sentence was not enough
  either — these hooks are two clauses, and the second one arrived flat.
- `avoid` compared raw pool lines against already-spoken capitalised ones, so it
  matched nothing and three clutches in a session opened identically.

**The map is no longer spoken**, and that fixed the pronunciation as a side
effect. espeak phonemises "Anubis" as `ˈænuːbˌɪs` — AN-oo-bis, stress on the
first syllable, where it should be `ɐnˈuːbɪs`. Respelling does not help; espeak
normalises "Anoobis" straight back to the same phonemes. Since the map was also
the dullest possible opening, dropping it settled both. Every line that does
ship was then checked through the phonemiser — a single wrong word in a
three-second hook is the whole hook.

Verified on a real clip: mean level over the first 2.5s went from −29.4 dB to
−21.7 dB with the voice in it, and the 5s mark measured −26.0 dB in both — so
the duck releases and the game comes back exactly as it was.

### What watching the first reel changed

**The drop has to land on a KILL, not on a slot.** The arrangement put the drop
inside the turn's slot and anchored the clip on its first kill, so on a 1v2
clutch the drop arrived two seconds past the kill that won the round -- on the
defuse afterwards. Two fixes:

- the turn is anchored on the **last** kill, because that is what wins a clutch
- `pre` is now *measured* -- `drop - slot_start` -- instead of being zero, so the
  anchor kill lands exactly on the drop whatever the snapped beat grid did

The slot is aimed so the drop falls about 60% of the way into it: the build-up
plays, the last kill hits on the drop, and the aftermath has somewhere to go.

**A track has more than one drop, and the arrangement needs the one it can
reach.** The biggest sustained rise in the test track is 20.0s in -- about 27
beats at 80 BPM, which cannot hold an eight-clip build-up. Aiming at it made the
arranger delete three clips to make the music fit, which is exactly the wrong
trade: the clips are the content. `find_drops` now returns every arrival ranked
by size (with non-maximum suppression, since the frames either side of one all
score nearly as well), and `_reachable_drop` takes the biggest one there is room
in front of. On the same track that is 110.2s, and all eight clips survive.

**Three orderings, because this is taste and taste needs evidence.**
`story.ORDERS` is `story` (chronological), `build` (weakest to strongest) and
`hook` (peak first). They are not equivalent: `hook` puts the turn at index 0,
so nothing has to play before the drop and it can therefore reach the track's
biggest arrival at 20.0s, while the other two have to settle for a later one.
All three are cut from the same clips and the same track so they can be judged
by watching.

### Watching the reels: the drop was on the build, not the arrival

Three reels went out for comparison and all three came back with the same
note -- the beat lands a second or two *after* the kill it is supposed to hit.
Measured on the track rather than argued about:

```
find_drops said        the music actually arrives
20.0s   -14.3 dB       25.0s   -4.2 dB, onset spike 1531
110.2s  -10.0 dB       112.2s  -4.2 dB, onset spike  377
```

**A sustained-rise measure peaks partway up the ramp**, because that is where a
rising leading window differs most from a flat trailing one. It reports the
BUILD. `_arrival` now takes each candidate and looks inside its window for the
first big onset at the point where the loudness has reached its plateau -- not
the loudest onset in the window, which can be a snare four bars into the
chorus. The two candidates above resolve to 24.75s and 112.00s, within a
quarter-second of the measured arrivals.

**The turn is sized by its own kill sequence.** A fixed 16 beats put the last
kill on the drop correctly and still opened the clip two kills into a
three-kill clutch: the kills spanned 13 seconds and the slot was 12. The slot
now opens `TURN_RUN_UP` before the round's FIRST kill and ends `TURN_TAIL`
after its last, rounded up to a phrase and capped -- 28 beats for that clutch.

**And the round clip itself was starting too late.** `build_rounds` anchored on
the last stand, on the reasoning that it is the moment the round became a
story. It is, but it happens after the team-mates die -- nine seconds after the
player's own first kill in this round -- so the clip opened past it and the
clutch appeared to start mid-fight. The anchor is now the EARLIER of the last
stand and the first kill.

All three were only findable by watching the output. None of them produced an
error, a warning, or an implausible number anywhere.

A fourth came out of chasing those: `_cut_and_mux` used a fixed `_beat` working
directory beside the output, so two reels rendered into the same folder deleted
each other's pieces on the way out. It does not fail -- it produces a reel
shorter than the arrangement it just logged, which is exactly the sort of thing
that gets blamed on the arranger. The directory is named after the output now,
and every slot that produces no piece, or a piece shorter than its slot, says
so in the log.

### Second round of reels: early is worse than late, and the grid was half used

**The drop was landing a fraction BEFORE the kill.** `_arrival` took the first
onset at the plateau, and a drop arrives over a few hundred milliseconds -- the
bass enters, then the kick lands. On the test track that put the mark at 24.75s
where the transient a listener hears is at 25.00s. It now takes the STRONGEST
onset in the first cluster (1.5s), which returns 25.00s and 112.00s against
25.00s and 112.05s measured by hand.

On top of that the anchor kill is placed `TURN_BIAS` = 0.10s BEFORE the drop
rather than exactly on it. The asymmetry is the whole point: a beat that lands
a fraction after the kill reads as the music answering it, and a beat that
lands a fraction before reads as a mistake. Two frames at 60fps is under the
threshold where anyone would call it late.

The arrival is also snapped to the beat grid when the two agree within 0.20s,
so the drop and the cuts run off one clock. When they disagree -- 112.00s is
0.36s from the nearest beat on this track -- the audio wins, because the grid
is the estimate.

**Cuts were on the beat and kills were not.** Every slot starts on a beat, so
every cut already landed on one; the kills inside them sat wherever a fixed
0.45s lead put them. Since a slot starts on a beat, rounding its run-up to a
whole number of beats puts the kill on the grid too -- twice the beats used,
for nothing.

Applied only to slots of `QUANTISE_MIN_BEATS` or more. Landing every cut AND
every kill on the grid is mechanical: the reel stops feeling edited to the
music and starts feeling generated by it. Short flash cuts keep their natural
lead, and the turn keeps the drop.

### And two bugs the first real clips showed up

**The burned caption contradicted the clip.** `overlay.caption_for` counted the
kills inside the window, so a 1v2 clutch that happened to contain three kills was
captioned "TRIPLE KILL" — true about the count, wrong about the clip. A round
clip already knows what it was, so the label wins where there is one:
`CLUTCH 1v2` becomes `1v2 CLUTCH`. Kill counts still caption a burst clip, which
has no label to use.

**Labels came out in the order `label()` happened to append them**, and
everything downstream takes `labels[0]` as "what this round was" — the filename,
the caption and the hook all do. A kill through smoke in a fast, bloody round
came out named `CHAOS`, because CHAOS is tested earlier in the function. They are
sorted by `rank_of` now, which is the same ranking that already decided the round
was worth cutting.

### And what the first watchable clips changed about the overlay

**The caption now stays up for the whole clip.** It was gated to the first 2.6
seconds on the reasoning that it had done its job by then and afterwards only
covered the gameplay it was advertising. That reasoning ignores how a Short is
actually watched — on a loop, and scrubbed into halfway through, where a viewer
arriving at second eight has nothing telling them what they are looking at. In a
"fit" vertical it sits in the blurred bar above the picture anyway, so leaving it
up costs no gameplay. `caption_seconds` still gates it for anyone who disagrees.

**The spoken hook is written out underneath, and fades when the voice stops.**
Its timing is the speech's own duration, which forced a reordering: the line is
now synthesised BEFORE the overlay pass rather than after it. That turned out to
be worth doing on its own, because the mix afterwards can then copy the video
through instead of re-encoding it — every narrated clip was paying for a second
full video pass to add an audio track.

Placed at 0.715 of frame height: below the gameplay, which occupies roughly the
middle third of a fit vertical, and above the branding at 0.855. Long lines wrap
at 30 characters. The box behind it fades with the text — checked rather than
assumed, by rendering a test clip and sampling the pixel under the box at three
times (0, 51, 0) -> (1, 89, 0) -> (0, 127, 0) against a background of (0, 128, 0).

Three things had to be got right in the drawing, and two of them were only
visible by looking at a real frame:

- **`text_align=C`.** drawtext left-aligns a multi-line block, so a wrapped
  two-clause hook came out ragged against a centred box.
- **`line_spacing=0`.** Its default leading leaves a gap you could park a third
  line in.
- **`newline="\n"` on the text file.** Python writes `\r\n` on Windows by
  default and drawtext renders the carriage return as a line of its own, so a
  two-line hook came out double-spaced with a blank line through the middle of
  the box. A ONE-line hook looked perfect, which is exactly why it survived the
  first look at the output.

The subtitle text goes through a file rather than `text=`: these are real
sentences with apostrophes and commas in them, and every one of those needs
escaping through two layers of filtergraph parsing if it is inlined.

**The default voice is male now** (`am_michael`), which is what a first-person
hook on this channel should sound like. The catalogue is read off the model by
name prefix rather than written down — Kokoro names every voice
`<accent><gender>_<name>` — so it reports what is installed, and 28 English
voices come out grouped. `autostream voice --sample` renders one wav each, which
is the only honest way to pick: a voice is the one thing in this package that
cannot be settled by measurement.

### 3. Story and beat assignment (`clips/story.py`)

`beatsync.py` already had the grid and the drop. What it did with them was move
the best clip INTO the drop's slot, which puts the end of the match in the
middle of the reel.

**So the clips stay in the order they happened and the music is offset instead.**
The arrangement is slid so that the turn's slot is the one containing the drop.
Nothing is reordered and the drop still lands on the peak.

```
opening   8 beats     the pistol round, or first blood
the slide 4 -> 2      compressed, and a LOST round gets half the room
THE TURN  16 beats    the peak, and the kill lands ON the drop (pre = 0)
the push  4 -> 2      flash cuts
close     8 beats     the last round, so the reel lands
```

Two things were wrong first:

- **The streak-breaker was the turn, outright.** It is the turn of the *match*,
  and making it the turn of the *reel* put the session's best clip — a 1v2
  clutch scoring 10.5 against the breaker's 8.5 — into a 0.9-second flash cut.
  The turn is now the most intense clip; a breaker only wins ties.
- **Phrase padding went on an act's last slot**, which is exactly the slot the
  density ramp had just made shortest, cancelling the acceleration it existed to
  create. It goes on the first slot now.

Also: the ramp applies to whichever act leads into the turn, not only to the
push. A session whose best moment is the second-to-last round has a long slide
and no push at all, and it should still speed up on the way in.

### And the clips got more room at both ends

The complaint that started this: CS2 clips were coming out **four seconds long**.
Short-form's 1.5s run-up and 2.0s tail are measured against respawn shooters,
where the kill is the whole moment. Counter-Strike is not that — the feed row
naming your kill lives a median of 5s, so a 2s tail cuts mid-announcement, and
there is no respawn, so a kill ends a slow approach that 1.5s does not show.

`Profile.pre_roll_min` / `tail_min` are floors under whatever style is chosen,
set to 3.0 and 4.0 for CS2 and to nothing for the two games whose numbers were
verified by eye. A single-kill short-form CS2 clip is now 7 seconds rather than
4, and "Full context" still gets its full 6.

The run-up is also where the spoken hook goes, which is the point: it is the one
part of a clip where nothing has happened yet.

---

## The promo reel (`clips/promo.py`)

**Wired up and verified** on `2026-08-22 13-06-33.mp4` (VALORANT, 23 kills).

The module already existed and nothing called it. Now the clips that fall below
`min_kills` are not cut on their own at all -- they are trimmed to a few seconds
each, run together and captioned as an advert for the channel. That caption is
the point: a single kill has nothing a caption could honestly claim about the
PLAY, but a claim about the channel is honest whatever the footage shows.

```
7 leftover singles -> VALORANT_promo_7clips_32s.mp4, 1080x1920
clips/ holds the 7 two-kill clips and no singles at all
```

Three things were wrong and are now tests:

- **The picker.** "Clips no caption could be found for" was a fair proxy while a
  caption meant a multi-kill. It stopped being one when round clips started
  captioning themselves from their labels. The rule is now the one the user
  actually sets: below `min_kills` is promo material, which at the default of 2
  is exactly "the single kills".
- **The length.** `piece_length()` asks for 5.0s a clip at seven clips, and every
  piece came out at 2.6s: the run-up had a floor and no ceiling, so
  `PROMO_PRE + PROMO_TAIL` won every time and a reel documented at 30-40s
  delivered **15.2s**. With a ceiling it delivers **32.0s**.
- **The hooks repeated.** Seven two-kill clips against a pool of two lines: the
  same sentence opened four of them, because `avoid` runs out and falls back.
  The pools now hold more lines than a session plausibly has clips of that size
  -- eight for a double. Seven clips, seven different lines.

## VALORANT round context -- which side lost the player

**Measured and landed.** The half that had no answer before.

`kind` only ever speaks about the local player, and most feed rows are other
people killing each other. A row is
`[portrait] KILLER [icon] VICTIM [portrait]` with each half in its owner's team
colour, so the colour of the victim's half names the side that just lost
somebody -- which is what alive counts, and therefore 1vN, would be built from.

```
157/157  kill rows read the victim as an enemy
 43/45   death rows read the victim as the player's own side
```

Both misses are single frames of rows that read correctly in every other frame,
so the per-event majority in `collapse` clears them.

Two simpler readings were measured and rejected first, and the second is the
instructive one:

- **The last 28% of the row.** 157/157 on kills and wrong on a self-kill. Agent
  portraits are photographs -- warm artwork that reads RED whichever team the
  player is on -- and a self-kill's bar is green with a red portrait at each
  end. Verified by eye on the frame at 1339s: `YuvaNeta [icon] YuvaNeta`.
- **The right half with the portraits excluded.** 154/157 and 34/45. The
  boundary between the two halves moves with how long the two names are, so a
  fixed fraction straddles it and red and green come within 10% of each other.
  The winner was noise.

What works is to clear the portraits and then walk a 24px window in from the
bar's right end until one colour beats the other three to one.

## VALORANT round boundaries -- attempted, NOT shipped

The other half of the round layer, and the half that stopped. Written up in
full because it got close enough that the next attempt should not start over.

**The score is the right signal.** Valorant's top bar is easier than CS2's in
every way but one: solid chevrons, big white glyphs, and the local team always
on the left, so there is no half-time reversal to detect.

```
region, fractions of frame     mine  x 0.412-0.452   theirs  x 0.552-0.592
                               both  y 0.022-0.062
```

**The one way it is worse is the one that matters: the panel is TRANSLUCENT.**
The same digit measures ~85 white pixels over a dark wall and ~3000 over bright
sky. That is exactly the failure `clips/hud.py` records for CS2's scoreboard,
and it kills any threshold: a first pass over the whole recording using a
white-pixel mask returned 45 "score changes", many of them with both sides
changing in the same second, which cannot happen.

**NCC reads it, and CS2's own digit templates work on Valorant's font.** At a
glyph height of 20px, checked by eye against two frames chosen for their
backgrounds:

```
1327s, score over bright sky    mine 7 (0.82)   theirs 0 (0.72)
1339s, score over a dark wall   mine 7 (0.82)   theirs 1 (0.70)
```

Brightness invariance doing exactly what it is for. Over 22 consecutive seconds
of one firefight the reader never wavered -- `7 (0.82)` and `0 (0.72)` every
second -- and then stepped `0 -> 1` once, at 22m16s, and held. **That is a round
boundary, read correctly, and verified by eye.**

### Why it still does not ship

Three measured problems, in order of how much they matter:

1. **Half the recording is illegible.** 1405 of 2752 frames give a confident
   read on both chevrons. Menus, loading screens and bright scenery take the
   rest. Rounds are ~100s and the sampling is 1 fps, so most rounds are still
   covered -- but not all.

2. **Rounds are demonstrably missed.** The 27 settled changes include steps of
   +2 and +3 on one side, which is not something a score does. Gaps run 13s to
   219s against a real cadence near 100s: the short one is spurious, the long
   ones are rounds that went unseen.

3. **One digit cannot tell 3 from 13.** `read_one` returns a single glyph, and
   `read_number` is unusable here -- it stitches a spurious second digit out of
   a one-digit region and returns 40, 43, 47 at every height from 16 to 24.
   A single digit is enough to DETECT a boundary, since every increment changes
   the units digit, but not to say the score.

**The failure mode is the reason to stop.** A missed boundary merges two rounds,
so the alive counts run past a reset and the player's side "loses" more than
five players in one round. What comes out is a confident, plausible
`CLUTCH 1v4` that never happened -- which is precisely what
`clips/rounds.py` and `clips/cs2_demo.py` are built to refuse rather than guess.

### What the next attempt should do

In this order, and none of it is speculative:

- **Cut Valorant digit templates from this footage** rather than borrowing
  CS2's. Confidence sits at 0.69-0.73 on "theirs" against CS2 glyphs, which is
  what forced the gate down to 0.64 and let noise in. `hud.py` records how to
  do it without hand-labelling: the round timer counts down one second at a
  time, so a run of consecutive frames labels itself.
- **Read two digits properly**, with per-digit cells rather than a search over a
  field that holds one.
- **Then refuse.** A score sequence validates itself -- every step is exactly
  +1, and it never goes down inside a match. A round layer that checks its own
  arithmetic and declines when it does not hold is the same contract
  `cs2_demo.align` already keeps, and it is what turns this from "close" into
  something that can be trusted.

The half that IS done -- which side lost the player, above -- is the half that
had no answer at all before, and it is landed and tested.

## Coming next

### Valorant round context

Half of it is done and written up above: which side lost the player reads at
157/157 on kills and 43/45 on deaths, and is landed and tested. What is missing
is round boundaries -- see "VALORANT round boundaries -- attempted, NOT shipped"
for the three measured reasons it did not ship and what the next attempt should
do first.

The replay route stays on hold: `michel-giehl/ValorantReplayParser` is real
(C#, .NET 10, parses `.vrf`) but marks Game State incomplete and exposes no
killer/victim attribution, and the `Playground` fork that `ValorantWebReplayer`
builds on was archived in July 2026.

### A cheaper fingerprint for the demo path

The demo needs only a handful of detected kill times to find itself in a
recording, but `align` measures its confidence as a share of ALL the demo's
kills — so scanning only the first ten minutes fails the 60% test even when the
alignment is perfect. Making the share window-aware (counting only demo kills
that map inside the scanned span, with an absolute floor on matched pairs) would
cut a CS2 clip job from about four minutes of scanning to under one. It has to
be done carefully: the same test is what refuses a wrong demo.

### A voice picker in the UI

54 voices, and only `config.yaml` can choose one. Also worth trying: a hook on
the reel's turn alone, rather than on every vertical.
