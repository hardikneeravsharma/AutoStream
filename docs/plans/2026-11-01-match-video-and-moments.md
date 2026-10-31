# The match video, and moments that are not kills

Asked for by the player on 2026-11-01: "how to make a good valorant match highlight video and
second one to identify moment based on audio levels, and how to use them in auto clipper to
find moment not with kills but with funny or exciting moments, consult with chatgpt and plan
then implement". ROADMAP *In flight* H1 and H2.

## 1. Research

### What the app already has

- **The match video exists.** `clips/match_recap.py` chooses the moments and names them,
  `clips/highlight.py` cuts them with a title, whips, whooshes, hit flashes and an outro.
  For Valorant the rounds come from Riot's own match record (`valorant_match.rounds_from`):
  every round's kills, its winner and the running score, and a round nobody died in placed
  between its neighbours. The switch ("Also make a recap of the match") is offered wherever a
  match record exists. The roadmap's "C2 Valorant half" notes were stale on all three points.
- **No Valorant recap had ever been made.** The only recaps on this machine are two Marvel
  Rivals ones from 2026-09-30.
- **153 Valorant match records** are cached (`Videos\AutoStream\matches`): exact kills,
  rounds, winners and ceremonies (ACE, CLUTCH) to measure against.
- **A game-agnostic audio reader exists**: `clips/loudness.py`, loud against a rolling median
  of the mix -- built to find gunfire in an uncalibrated game.

### Today's recap of one real match

`2026-10-25 18-45-24.mp4` (4.6 h, 1080p60) holds a competitive match on Bind, lost 9-10,
19 rounds, 16 kills; Riot's record lines up by the clock. Rendered exactly as the job does:
**11 moments, 158 s**: Last Alive, Last Alive, *(unnamed)*, Thrifty, Thrifty, 3K In 5s,
Last Alive 1v4, *(unnamed)*, *(unnamed)*, 2K, 2K. Seen at once: three moments have no name
and so no chapter; names repeat; the title card reads "VALORANT | 9-10 - 16 KILLS" with no
map or agent; nearly every moment is a 12 s single kill; the round's context (score, round,
alive count) is never on screen.

### What a good match video is, from outside

- Long-form channels: "15 Times Shroud Was a Beast in VALORANT" is 6m32s -- an 18 s intro,
  then 14 moments of 15-50 s (average 28), each chapter named for the play.
- Clip guides: open on the payoff or the tension; restore the context fast (score, round
  timer, who is alive); give a clutch its setup. A 9:16 crop loses the minimap and kill feed.
- Highlight-detection research: Ringer & Nicolaou (2018) find stream highlights from the
  game, the streamer's face and the audio together, the audio read for arousal; golf
  highlights weight the crowd's cheer and the commentator's excitement highest; a League
  system reads the caster's pitch and volume. **A person's reaction is the strongest single
  signal of excitement.**

### The audio we have

- OBS records **three audio tracks**: 1 the mix, **2 the microphone alone**, 3 the game alone
  (`obs.split_audio_tracks`; confirmed on two real recordings). The player's reaction is on a
  track of its own, without the gunfire.
- The mic is **noise-gated**: silent 65-70 % of the time. Against a rolling median (what
  `loudness.py` does) every word is a peak -- 206 in 40 minutes.
- Measured instead against **the player's own speaking level** (the median of voiced frames,
  -38.9 dBFS here): runs 10 dB over it for 0.4 s, merged within 3 s, scored in dB-seconds
  over the line -> 96 reactions in 40 minutes.
- **Ground truth**: the player hand-cut a "missed 1v4 clutch RAGE" meme from this recording
  (`BINDMISSED1V4clutch_RAGE.fcproj`, source 691.8-728.6 s). The measure finds a 5.4 s run
  20.8 dB over their voice at 712 s -- **ranked 2nd of 96**. That moment is not in today's
  recap, because the recap knows only kills.
- Cost: two tracks of 40 minutes read in about 2 s.
- **What a sound is** needs a classifier. YAMNet (AudioSet; 521 classes including Laughter,
  Giggle, Chuckle, Belly laugh, Shout, Yell, Screaming, Cheering; 0.96 s frames every 0.48 s;
  Apache-2.0) exists as ONNX (about 15 MB); `onnxruntime` is already installed for the voice
  model. It would run on the mic track only, around candidate reactions.

Sources: [Ringer & Nicolaou 2018](https://arxiv.org/pdf/1807.09715),
[golf highlights](https://arxiv.org/pdf/1707.07075),
[LoL real-time highlights](https://ceur-ws.org/Vol-4055/icaiw_wdea_5.pdf),
[YAMNet](https://www.tensorflow.org/tutorials/audio/transfer_learning_audio),
[YAMNet ONNX](https://huggingface.co/audiomagic/yamnet-onnx),
[Eklipse: Valorant clips](https://eklipse.gg/help/how-to-edit-valorant-clips-with-eklipse/),
[autoclip: esports clipping](https://autoclip.dev/blog/esports-competitive-gaming-clip-guide).

## 2. The plan (with ChatGPT, 2026-11-01)

Put to ChatGPT in the "Valorant Reel Design Review" chat with today's Bind recap attached and
the measurements above. Its architecture: **two independent detectors -- gameplay (kills,
clutches, aces, round-deciding plays) and reactions (the mic) -- feeding one moment
curator.** A kill is a gameplay event, a reaction a human one; neither needs the other to be
found. Its verdict on today's recap: the 2:50 length is right; what is wrong is *which*
moments and *their context* -- a 12 s single kill does not say why it mattered.

### Reactions (H2)

- **Detect** on track 2 against the player's own speaking level -- confirmed as the primary
  measure: smoothed 0.3 s, +10 dB, at least 0.4 s, merged within 3 s, ranked by dB-seconds
  over the line. Never a hard-coded level. The baseline from voiced, normal-speaking frames
  only, reactions left out of it; a clipped (saturated) mic is a warning, not a high score.
  Keep the onset, the end and the peak separately.
- **Classify** with YAMNet *around candidates only*, never the whole recording; YAMNet for
  what the sound is, the 20 Hz envelope for where it starts and ends.
  - LAUGH: Laughter, Giggle, Snicker, Belly laugh, Chuckle/chortle. A confident laugh may
    qualify without the +10 dB -- a second way in, not a replacement.
  - HYPE: Yell, Screaming, Whoop, Cheering, Bellow; Shout supports but never decides alone.
  - **No RAGE label from YAMNet** -- it has no such class, and Screaming is joy, fear and anger
    alike. Without a calibrated emotion classifier and supporting context (a failed clutch, a
    death, a lost round) it is **LOUD REACTION**.
  - YAMNet's scores are not calibrated probabilities: per-class thresholds are set on labelled
    AutoStream mic recordings for at least 85 % precision; unsure stays unlabelled.
- **Rank**: 40 % integrated loudness over the line, 20 % peak, 25 % class confidence, 15 %
  game context, each as a percentile within the session. A quiet, unmistakable laugh is not
  thrown away for being quiet.
- **Where the clip starts and ends** (as important as finding it): back up to 20 s for the
  cause in the same round (contact, last alive, a teammate's death, a miss, the plant) and
  start 1-2 s before it, else 8 s; after it, until the mic is back to normal for 1.5 s, plus
  2-3 s; to the round's end plus 1 s if that is within 12 s; 40 s at most. The hand-cut rage
  meme starts about 20 s before its reaction.

### In the clipper

- A reaction inside, or just after, a kill clip **of the same event** is merged into it (the
  clip gains the label and, if needed, length); standalone otherwise -- a laugh with no kill,
  a failed clutch with its whole context.
- **Index every reaction; cut only the best 10 an hour** by default, the rest listed for the
  player to pick. 2.4 candidates a minute must not become 150 clips.
- `moment_type` on a clip: KILL / REACTION, with the reaction's own times beside the clip's.

### The match video (H1)

- **2.5-4.5 minutes, 8-12 moments**, length by what the moment is: a 2K/3K 10-18 s, a 4K or
  ace 15-25 s, a clutch or round-deciding play 20-35 s, a reaction 8-20 s; title 1.5-2.5 s,
  outro 3-5 s. **A lone kill is not a highlight** unless something makes it one.
- **Ranked**: match-deciding or overtime rounds, 1v3/1v4 clutches and aces first; then 4Ks,
  fast 3Ks, round-winning retakes and holds, thrifties; ordinary 2Ks conditional; a lone kill
  low. An ace in a dead round does not beat a match-point retake. Gameplay score
  0.35 impact + 0.30 round importance + 0.20 reaction + 0.15 clarity/uniqueness; a reaction
  moment 0.40 strength + 0.30 class confidence + 0.20 game connection + 0.10 quality.
- **Order: a 4-6 s cold open from the strongest moment, then the title, then match order.**
  The cold open is not the whole moment twice.
- **Round context on screen**: 1.5-2.5 s before each moment -- round, side, score before it,
  the situation (1v3), economy only when known, the event's name -- then out of the way;
  during the play only alive counts, the result and the score after. Nothing inferred shown
  as fact.
- **Chapters never blank, never the same twice**: "1v3 B Retake", "Thrifty Round 6", "Missed
  1v4 + Rage" (once there is evidence for rage); the fallback is "Round 08 - 2K".
- **Title** "VALORANT Bind | 9-10 Loss | 16 Kills | [Agent]"; a loss is not hidden. Thumbnail
  text 3-5 words.
- **Losses and deaths with a big reaction belong**, labelled honestly.
- **Reactions in the recap**: 6-10 gameplay moments and 2-4 reaction moments where they add
  something; a merged moment counts once.

### Order to build, with acceptance

1. **Reaction detection** -- recall of the player's standout reactions at least 90 %, the
   candidates surfaced at least 75 % precise, on labelled recordings.
2. **Classification and clips** -- YAMNet, the clip boundaries, the 10-an-hour cap; at least
   85 % precision per label on held-out labelled mic audio, unsure left unlabelled.
3. **Merge with gameplay** -- reactions tied to kills, rounds, deaths and clutches; no two clips
   of one event.
4. **The recap director** -- ranking, round context, chapter names, cold open, title.

### What needs the player

- **Labels.** One ground truth exists (the rage meme). The acceptance numbers need more: a
  handful of sessions where the player marks the moments they would have kept. Until then the
  thresholds are ChatGPT's starting values and the measured ranking above.
- **The YAMNet model** is a download (about 15 MB, Apache-2.0); like the voice model it is
  fetched only with the player's yes.

## 3. What was built, and the reviews

v2.7.0 -- see the ROADMAP Progress row for the whole list. The recap was rendered from the Bind
match of 2026-10-25 and sent to ChatGPT each round:

| | Rating | What it said |
|---|---|---|
| v1 (today's recap) | 4.6/10 | Right length; wrong moments and no context |
| v2 (first pass) | 7.4/10 | "From a kill compilation towards a match story". The cold open showed the buy phase; the card sat on the facecam; "+ reaction" should be "+ Player Reaction"; no agent; a faint title |
| v3 (second pass) | *see below* | Re-rendered correctly aligned (v1 and v2 were 107 s early -- my script lined the record up by the clock alone; the job fingerprints) |

Second-pass rules, applied: the cold open holds its kill inside the first two seconds; the card
sits top centre under the score bar for at most 1.8 s and leaves 0.25 s before a kill (a
safe-area search -- measuring the facecam, HUD and kill feed per recording -- is left for later);
neutral reaction words; the agent from a versioned table, omitted when unknown; a dark plate
behind the title.
