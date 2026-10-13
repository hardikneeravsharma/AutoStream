# Style spec — "Fast-paced headshot"

**Status:** specified, not implemented. Nothing in `autostream/` builds this yet.
**Written for:** the next agent or contributor who implements it. Assumes you have read
[CLAUDE.md](../CLAUDE.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

This document specifies a new Studio style. Every number in it was **measured off a
working reel**, not chosen by taste. The reference build is:

```
C:\Users\user\Videos\AutoStream\clips\reels\MONO-ALL-HEADSHOTS-Murder-nearfit.mp4
```

That file was cut by hand with ffmpeg outside the app. The job here is to put its
genetics inside the app so the style can be picked from the Studio page like any other.

Watch the reference before you start. Numbers below describe it; they do not replace it.

---

## 1. What the style is

A monochrome, headshot-only reel that **flashes to photographic negative on the beat**.
Cuts sit at one or two beats, tightening to a burst, then resolving on a real multi-kill.
The picture is hard black-and-white with almost no midtones.

The look is not invented. It was reverse-engineered from an anime edit (Jujutsu Kaisen)
the user supplied, and the grade was tuned until it measured the same. See §6.

What makes it different from `chaos`, the closest existing style:

| | `chaos` | `fast-paced headshot` |
|---|---|---|
| Effects keyed to | each kill | **the beat grid** |
| Grade | crunch, colour | monochrome, extreme S-curve |
| Signature | flashes and shake | **negative flip** |
| Kill filter | all kills | **headshots only** |
| Text on screen | captions | **none** |

The last two rows are user requirements, not taste. See §11.

---

## 2. Terms used below

| Term | Meaning |
|---|---|
| **beat** | one beat of the song. In the reference, `0.5 s` exactly |
| **bar** | four beats. In the reference, `2.0 s` |
| **drop** | where the song's low end slams in |
| **v-time** | time in the finished video, `0` at the first frame |
| **body** | everything before the end card |
| **panel** | the gameplay rectangle inside a letterboxed frame |
| **full-bleed** | the gameplay fills all 1080×1920; no bands |

---

## 3. The spine: lock to the song first

Everything else hangs off this. Get it wrong and nothing downstream reads right.

### 3.1 Find the tempo exactly

Do **not** trust a round number. Measure it, then snap to the nearest exact value if the
score is within noise — a track produced at exactly 120 or 150 BPM gives a whole number of
frames per beat at 60 fps, which makes every cut frame-exact.

Method that worked (phase-locked comb, better than plain autocorrelation here because the
onset envelope is noisy with vocals):

1. Decode mono at 22050 Hz.
2. STFT, `N=1024`, `H=256`. Spectral flux = `max(0, diff(log1p(S*10))).sum(axis=bins)`.
3. For each candidate BPM in `[119, 121.5]` step `0.02`, and each offset in `[0, beat)`
   step `0.01`, score `flux[|((t-offset+beat/2) mod beat) - beat/2| < 0.03].sum()`.
4. Take the best. Then test the nearest whole BPM; if it scores within ~0.1%, **use the
   whole number**.

Reference result: locked **120.000 BPM**, beat `0.50000 s`, bar `2.0 s`.
At 60 fps that is **30 frames per beat, 120 per bar** — no drift, ever.

### 3.2 Find the drop, and let it set the phase

The onset grid's phase is unreliable — hi-hats on the off-beat pull it half a beat out.
The reference's comb said offset `0.25 s`, which would put beats at `…16.75, 17.25…`.
The actual drop is at `17.00 s`. **The drop wins.** Beats run `… 16.5, 17.0, 17.5 …`,
bars on odd seconds.

Find the drop by RMS step, not by onset:

- 0.25 s RMS windows across the intro.
- The drop is the first window where RMS jumps **≥ 10 dB** above the preceding ~2 s and
  stays up.
- Reference: `-13.4 dB` at 16.0 s → `-1.1 dB` at 17.0 s. A 12 dB step. Drop = **17.00 s**.

A naive "first big low-end transient" detector fires on intro hits and is wrong. It
returned `1.03 s` and `10.06 s` on this track. Do not use it.

### 3.3 Where the reel starts

```
song_start = drop − 2 bars
```

Reference: `17.0 − 4.0 = 13.0 s`. The reel opens two bars before the drop, so the bass
lands at **v-time 4.0 s**, on the fifth cut. That short build is what makes the drop hit.

Check the song still has energy for the whole reel. The reference track runs full from
17 s to 128 s; the reel only needs 13.0 → 53.6 s.

---

## 4. Shot selection

### 4.1 The pool

Headshots only. The reference reel drew from 67 distinct headshot moments across 41 clips
and used 38.

**Dedupe by `(clip name, kill time)`, not by file path.** AutoStream writes duplicate
recording folders (`..._1918_VALORANT` and `..._1918_VALORANT_2`) that contain the *same
round*. Treating those as two clips is how an earlier reel showed three kills twice, two of
them inside the last four seconds. 67 distinct moments came from 72 raw rows.

### 4.2 Grade every candidate by eye before cutting

This is the step that cannot be skipped and cannot be done by reading code.

1. Extract one frame per candidate at `kill_time + 0.08 s`, cropped to the framing you
   will use.
2. Tile them into contact sheets (12 per sheet works).
3. **Look at them.** Grade A–F:

| Grade | Means | Use |
|---|---|---|
| **A** | enemy large, centred, clearly being hit | hooks, act openers, finale |
| **B** | enemy visible and legible | the body of the reel |
| **C** | enemy small, far, or partly obscured | burst shots only |
| **D** | enemy barely findable; smoke, distance | burst filler, sparingly |
| **F** | no enemy, death cam, ult screen, blank wall | **never** |

Reference mix across 38 shots: **A 8, B 19, C 8, D 3, F 0.**

C and D grades are fine *inside the one-beat burst* — at 0.5 s in monochrome with a
negative flash over the top, a weak frame reads as texture. They are not fine at two beats.

### 4.3 Hard exclusions

- **F-grade frames.** Death cameras and ult cinematics have no kill in them.
- **Round-end accolade banners.** Valorant draws `WON`, `CLUTCH`, `FLAWLESS` after a round
  resolves. Two traps here:
  - A `WON` banner in the first two seconds reads as "video over" and is penalised in the
    user's own `RATINGS.md`.
  - **`CLUTCH` can be the enemy's.** An earlier cut closed on an enemy clutch banner — the
    reel ended on the user losing the round. Verify whose accolade it is, or cut before it
    appears. Trim the shot so the banner never enters frame.
- **Any clip supplying more than 3 shots.** Variety in a montage is the backdrop changing;
  six shots from one round reads as one long round.

### 4.4 Narrative labels come from the clip name, never from the screen

`VALORANT_16_LAST-ALIVE-1v5_…` is AutoStream's own detection of the user's state and is
trustworthy. Text burned into the game frame is not — it may describe the enemy. This
distinction caused a real error; keep it.

### 4.5 Real multi-kills

Consecutive headshots **< 2.5 s apart** in the same clip are a showable multi-kill. Play
them as **one continuous shot**, never two cuts. The reference found six such pairs and
closed on the tightest usable one (0.45 s apart).

---

## 5. Structure

All lengths in **beats**. One beat = 30 frames at 60 fps.

### 5.1 The realised shape (reference reel)

| Section | Shots | Beats each | Beats | v-time |
|---|---|---|---|---|
| Build | 4 | 2 | 8 | 0.0 → 4.0 |
| Act I (the drop) | 12 | 2 | 24 | 4.0 → 16.0 |
| Act II | 10 | 2 | 20 | 16.0 → 26.0 |
| Burst | 10 | 1 | 10 | 26.0 → 31.0 |
| Slow-motion breath | 1 | 4 | 4 | 31.0 → 33.0 |
| Finale (the double) | 1 | 6 | 6 | 33.0 → 36.0 |
| **Body** | **38** | | **72** | **36.0 s** |
| End card | — | — | — | 36.0 → 40.6 |

Mechanically that is `26 × 2 beats`, `10 × 1 beat`, `1 × 4`, `1 × 6`.

### 5.2 Rules, not just this shape

- **Build is always 2 bars.** Long enough to set the grid, short enough not to cost the hook.
- **Cuts halve once.** Two beats through the body, one beat for the burst. Do not introduce
  a third rate; it stops reading as an acceleration.
- **Exactly one slow-motion beat**, immediately before the finale, at `0.6×`. It is the
  only moment the reel breathes. More than one and the acceleration collapses.
- **Finale is the longest shot in the reel** and is a real multi-kill. 6 beats.
- **Body length must be a whole number of bars.** 72 beats = 18 bars.

### 5.3 Pre-roll (how much of a shot comes before its kill)

| Shot length | Pre-roll | Aftermath |
|---|---|---|
| 6 beats (3.0 s) | 1.60 s | 1.40 s |
| 4 beats (2.0 s) | 1.20 s | 0.80 s |
| 2 beats (1.0 s) | 0.62 s | 0.38 s |
| 1 beat (0.5 s) | 0.30 s | 0.20 s |

For the finale, pre-roll is measured to the **first** kill; the second lands 0.45 s later,
leaving ~0.95 s of aftermath.

For a slow-motion shot, pre-roll is in **output** time: source pre-roll is
`pre_out × speed`, and source duration is `out_duration × speed`.

Why these and not "minimum 0.8 s": the kill needs cause and effect, but at one beat there
is no room for it. The burst buys its density by giving that up deliberately, which is why
it is short and comes late.

---

## 6. The grade

### 6.1 The chain

Applied to the gameplay **before** any compositing (see §7.3 — this ordering matters):

```
hue=s=0,
curves=all='0/0.0155 0.200/0.0965 0.475/0.5635 0.690/0.988 1/1',
eq=contrast=1.265:brightness=0.0195:gamma=1.005,
unsharp=3:3:0.55:3:3:0.0
```

The curve is the whole style. It is a steep S that crushes everything below ~0.20 toward
black and runs everything above ~0.69 into white, leaving very little middle. Slope through
the midsection is about **1.97** — nearly double.

### 6.2 The targets it was tuned to

Measured over the whole video at 4 fps, 120×213, linear-ish luma
`0.2126R + 0.7152G + 0.0722B`:

| Measure | Anime reference | This style (achieved) |
|---|---|---|
| Mean saturation | 0.035 | **0.002** |
| Pure black (`<0.05`) | 20.6% | **24.8%** |
| Midtones (`0.3–0.7`) | 29.8% | **25.9%** |
| Pure white (`>0.95`) | 16.5% | **10.2%** |
| Mean luma | 0.472 | **0.389** |

Whites land low and that is **correct, not a miss**. Valorant maps are darker than anime
line art on a white page; three tuning passes showed that pushing the top of the curve
further blew out player models before it moved the percentage much. Treat the reference row
as a direction, the achieved row as the acceptance range:

```
saturation  < 0.01        black  20–28%
midtones    22–32%        white   8–18%        mean luma 0.36–0.45
```

### 6.3 Against the existing grade table

`studio.py` already has `g07 "Monochrome" = (0.0, 1.2, 0.0, "")` — saturation 0, contrast
1.2, no static filter. **That is not this look.** It desaturates but keeps a normal tone
curve, so it lands around 30–35% midtones with no crush.

Add a new grade rather than changing `g07`, which existing projects reference:

```python
# Hard monochrome: an S-curve steep enough that almost nothing survives in the
# middle. Measured against an anime edit, not chosen -- see docs/STYLE-FAST-PACED-HEADSHOT.md
"g13": (0.0, 1.265, 0.0195,
        "curves=all='0/0.0155 0.200/0.0965 0.475/0.5635 0.690/0.988 1/1'"),
```

Note `GRADES` rows are `(saturation, contrast, brightness, static_filters)`; `gamma` has no
slot, so either fold the 1.005 into the curve (it is nearly a no-op) or widen the tuple.

---

## 7. Framing

Three framings ship. All output **1080×1920, SAR 1:1**.

### 7.1 Crop (full-bleed)

```
crop=608:1080:656:0, scale=1080:1920:flags=lanczos, setsar=1
```

608 is `1080 × 9/16`. The kill is always at the crosshair and the crosshair is always
centred, so the centre third keeps every kill. It loses the minimap and most of the kill
feed. Biggest, most immersive picture.

### 7.2 Near-fit and full-fit

| | Source crop | Panel | Overlay Y | Bands |
|---|---|---|---|---|
| **near-fit** | `crop=1440:1080:240:0` | 1080×810 | 555 | 555 top and bottom |
| **full-fit** | none | 1080×608 | 656 | 656 top and bottom |

Near-fit keeps the centre 75% of the width — minimap, scoreboard and most of the kill feed
survive, and the picture is a third taller than full-fit. **It is the one to default to.**
Full-fit crops nothing but leaves the gameplay at about a third of the screen height.

### 7.3 The backdrop — and the ordering that makes it work

```
scale=300:534:force_original_aspect_ratio=increase, crop=300:534,
gblur=sigma=15, scale=1080:1920:flags=bilinear,
eq=contrast=0.35:brightness=-0.28:saturation=0.75, setsar=1
```

Blur small, then scale up. A `sigma=42` blur at full resolution costs many times more and
looks identical once it is this soft.

**Build the backdrop from the already-graded panel, not from the raw frame.** This is not
a style choice, it is a bug fix. Composing first and grading afterwards means the
monochrome curve lifts the blurred backdrop too; the first attempt measured the bands at
luma **0.000** — pure black. The user saw bare letterbox bars, not a backdrop.

Correct order:

```
panel → look → unsharp → beat effects → split
                                         ├── backdrop (blur, darken)
                                         └── panel
                                       overlay → pump → …
```

Acceptance: band luma **0.10–0.18**. Reference measures 0.116 (bottom) / 0.163 (top).

Add a 2 px rule at each panel edge so the picture reads as placed rather than floating:

```
drawbox=x=0:y={OY-2}:w=iw:h=2:color=white@0.16:t=fill
drawbox=x=0:y={OY+panel_h}:w=iw:h=2:color=white@0.16:t=fill
```

### 7.4 `setsar=1` is mandatory

Scaling to a new shape makes ffmpeg record the old display aspect in the **sample** aspect
ratio. The letterboxed builds shipped once with `SAR 256:81`, so a 1080×1920 file reported
`DAR 16:9` and every player stretched it into a wide strip. It looked broken because it
was.

Put `setsar=1` after every `scale`, after the overlay, and after `zoompan`. Assert on the
finished file:

```
ffprobe -select_streams v -show_entries stream=sample_aspect_ratio,display_aspect_ratio
→ must be 1:1 and 9:16
```

---

## 8. The beat engine

This is what the style is named for. Every expression below uses `it` (zoompan's input
time) or `t` (everything else), in **v-time**.

### 8.1 The intensity gate

```
G  = if(lt(it, DROP), 0.45, if(lt(it, ACT3), 1, 1.12))
Gt = same with t
```

`DROP = 4.0` (v-time), `ACT3 = 26.0`. The build runs at 45% so the drop has somewhere to
go; the last act runs 12% hotter so the finale does not feel like more of the same.

### 8.2 Screen pump — every beat, harder on the bar

```
z = 1.025 + (G)*( 0.019*exp(-mod(it,BEAT)/0.080)
                + 0.021*exp(-mod(it,BAR )/0.105) )
x = iw/2-(iw/zoom/2) + (G)*10*exp(-mod(it,BAR)/0.072)*sin(it*155)
y = ih/2-(ih/zoom/2) + (G)*7 *exp(-mod(it,BAR)/0.072)*sin(it*198)
```

Applied as:

```
zoompan=z='…':x='…':y='…':d=1:s=1080x1920:fps=60, setpts=N/60/TB, setsar=1
```

The **2.5% base zoom is load-bearing** — without it `zoompan` clamps x/y to zero range at
`zoom=1` and the shake does nothing. The `sin(it*155)` / `sin(it*198)` pair is ~25 Hz on
two incommensurate frequencies so the shake never repeats visibly.

> **`setpts=N/60/TB` after `zoompan` is not optional.** Without it `zoompan` emits broken
> timestamps and a following `fps` filter inflates the stream without limit. A 2-second
> test slice produced **513 seconds and 30,789 frames**, exhausted RAM and disk, and froze
> the machine. Always also pass `-frames:v <expected>` as a hard stop.

### 8.3 Negative flip — the signature

```
# full-bleed: one frame on every beat, three on every bar line
negate=enable='gte(t,{DROP-BAR})*( lt(mod(t,{BEAT}),0.0167)
                                 + lt(mod(t,{BAR}),0.0500) )'

# letterboxed: bar lines only
negate=enable='gte(t,{DROP-BAR})*lt(mod(t,{BAR}),0.0500)'
```

Summing the two terms is deliberate: `enable` treats any non-zero as on, so a bar line
(both terms 1) stays on through the longer window instead of two `negate` filters
cancelling each other back to positive.

It starts one bar before the drop, so the build ramps in.

**Why letterboxed is different.** Over flat bands a whole-frame invert twice a second is a
full-screen white strobe — 64 of them in 36 seconds. That is punishing to watch and a
photosensitivity concern. On bar lines it is 18, which still reads.

Counts in the reference: **64 flips** full-bleed, **18** letterboxed.

### 8.4 Light kick — every beat

```
eq=brightness='({Gt})*0.029*exp(-mod(t,{BEAT})/0.058)':eval=frame
```

`eval=frame` is required or the expression is evaluated once at init and does nothing.

### 8.5 Drop punctuation

```
drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill:enable='between(t,{DROP-0.034},{DROP-0.001})'
```

Two frames of black immediately *before* the drop. The snap into the bass is worth more
than any flash on it.

### 8.6 Vignette

`vignette=angle=PI/9` on **full-bleed only**. On a letterboxed frame it darkens the flat
bands into a visible oval and looks like a fault. Omit it there entirely.

### 8.7 Order of the chain

```
look → unsharp → [backdrop split/overlay if letterboxed] → zoompan → setpts → setsar
     → brightness kick → negate → vignette (full-bleed only) → drop drawbox
```

### 8.8 How this differs from the existing part system

`studio.py` already has the two primitives:

- `k12 "Invert frame"` → `negate=enable='{_between(kt, kt+dur)}'`
- `k06` → `rgbashift=…:enable='{_between(kt, kt+dur)}'`

Both key off **`kt`, the kill time of the shot they are in**. This style keys off the
**beat grid, independent of where kills fall** — that is the entire point, because it is
what lets a 1.0 s shot carry two beats of effect.

So this needs a mechanism the parts bin does not currently have: a *reel-level* effects
pass that runs over the concatenated body with absolute v-time, after the per-shot render.
Options, cheapest first:

1. **A post pass over the body.** One extra encode of the whole reel (~20 s for 36 s at
   1080×1920 on NVENC). Simplest, and what the reference build does.
2. **Per-shot with an offset.** Pass each shot its own `start` and write
   `mod(t + start, BEAT)`. Avoids the extra encode but every part needs threading through,
   and a slow-motion shot breaks the mapping.

Recommend (1). The extra encode is cheap and it keeps the grid in one place.

---

## 9. Audio

Unchanged from the other styles except the levels, which were measured.

```
music : loudnorm=I=-15:TP=-2:LRA=11, afade=t=out:st={TOTAL-3.1}:d=3.1
game  : (volume=5.0 applied per segment), loudnorm=I=-26:TP=-6:LRA=7, highpass=f=90, apad
mix   : amix=inputs=2:duration=first:dropout_transition=0:weights='1 0.8',
        alimiter=limit=0.89:attack=4:release=60,
        loudnorm=I=-14:TP=-1.3:LRA=11
```

Game audio sits about 11 LU under the music — gunfire and headshot dings come through
without muddying it. The source tracks are quiet (mean ≈ −42 dBFS), hence the `volume=5.0`
lift at segment time.

Slow-motion shots get `atempo={speed}` **and** `volume=0`. Slowed game audio wobbles; the
music covers the gap.

Measured on the reference: **−14.2 LUFS, true peak −5.4 dBFS.** Target `−14 ± 0.5 LUFS`
and keep the peak at or below `−3 dBFS` so platform normalisation does not squash it.

---

## 10. The end card

4.6 s, hard cut, **video only** — any audio on the card asset is discarded and the music
bed runs unbroken underneath.

```
scale=1080:1920:flags=lanczos, setsar=1, fps=60,
<glow sweep overlay>,
fade=t=in:st=0:d=0.11:color=white,
vignette=angle=PI/11,
fade=t=out:st={DUR-0.45}:d=0.45
```

- **Fade in *from white*, not a dissolve.** The join reads as an impact.
- **No push-in if the card asset already moves.** Two motions fight.
- **Glow sweep**: a soft diagonal band crossing once at ~0.45 s. Built as a 2160×1920 RGBA
  gaussian band translated across with `overlay=x='-W+(t-0.45)/0.85*2.1*W':eval=frame`.
  This is the app's own lyric `glow` look (`clips/lyrics.py`, `\bord18 \blur22` bloom)
  borrowed as a highlight.

On a monochrome reel the card is the **only colour in the whole video**. That is the point
— it lands as a payoff rather than a sign-off. Do not desaturate it to match.

---

## 11. Hard user requirements

These are not preferences; they were given explicitly and reversing them is a regression.

1. **No text over the gameplay.** No kill labels, no counters, no titles. An end card is
   fine; anything over a kill is not.
2. **Headshots only.**
3. **No kill shown twice** in one reel.
4. **Never claim a multi-kill the shot does not show.** A "TRIPLE KILL" label over a 0.8 s
   one-kill shot is what this style was built to replace.

---

## 12. Verification

Run all of these on the finished file. Each one caught a real bug.

| Check | Command / method | Pass |
|---|---|---|
| **Aspect** | `ffprobe … sample_aspect_ratio,display_aspect_ratio` | `1:1` and `9:16` |
| **Frame count** | `nb_frames` vs `beats × 30 + card` | exact |
| **Grade** | sat / black / mid / white / mean luma | §6.2 ranges |
| **Band luma** (letterboxed) | mean luma of rows above and below the panel | 0.10–0.18 |
| **Beat lock** | per-frame mean luma, take the 24 largest frame-to-frame jumps, measure `t mod beat` | **≥ 80%** within 60 ms of a beat |
| **Loudness** | `ebur128=peak=true` | −14 ± 0.5 LUFS, peak ≤ −3 dBFS |
| **Dead frames** | per-frame mean luma | none `<0.03` or `>0.97` except the intended drop flash |
| **Banners** | contact sheet at 1 fps, look | no round-end accolades |

The beat-lock check is the one that proves the engine is actually synced. Reference scored
**21 of 24** within 60 ms, most within 2 ms.

---

## 13. Pitfalls, each of which cost real time

1. **`zoompan` without `setpts=N/60/TB`** → runaway output. See §8.2. Froze the machine.
2. **Never run concurrent ffmpeg jobs.** Three at once plus a full-file `-count_frames`
   decode exhausted RAM and pinned disk I/O at 100%. One at a time, always with
   `-frames:v` as a cap.
3. **`setsar=1` everywhere.** See §7.4.
4. **Backdrop built before the grade gets crushed.** See §7.3.
5. **`-t` placed after `-i` is an *output* limit.** For a slow-motion shot you need more
   *source* than output, so `-t` must come **before** `-i` or the shot comes up short. One
   segment rendered 95 frames instead of 144 this way.
6. **`eq` expressions need `eval=frame`.**
7. **Round-end banners, and whose they are.** See §4.3.
8. **A full-frame invert on a letterboxed picture is too harsh.** See §8.3.
9. **Don't `-count_frames` a large file** to check length; read `nb_frames`.

---

## 14. Implementation sketch

### 14.1 The `Style` entry

```python
Style("fasthead", "Fast-paced headshot",
      "Headshots only, in hard black and white, flipping to negative on the beat. "
      "Cuts at one or two beats and a real multi-kill to close.",
      (),                       # refs: the anime edit is not a public id
      intro="i08", outro="e05",
      cuts=("t01",),            # hard cuts; the flip carries the energy
      kill=("k01snap",), hero=("h01",),
      speed="s00", hero_speed="s00", camera="c00",
      grade="g13", vignette=True, pre_share=0.62,
      kill_pool=("k01snap",), transition_pool=("t01",),
      hero_pool=("h01",), camera_pool=("c00",),
      speed_pool=("s00",), energy=0.0),
```

`energy=0.0` and single-entry pools are deliberate: **this style's effects do not come from
the parts bin.** They come from the reel-level beat pass (§8.8). Leaving the pools rich
would stack per-kill effects on top of the beat engine and muddy it.

### 14.2 Work items

| # | Item | Notes |
|---|---|---|
| 1 | `g13` grade | §6.3. New row, don't edit `g07` |
| 2 | Reel-level beat pass | §8. New stage after concat, before the card |
| 3 | Tempo + drop detection | §3. `beatsync.py` is the natural home |
| 4 | Headshot-only + dedupe + reuse cap | §4. `hs_only` already lands in `clips/arrange_fit.py` (~L803); the `(name, kill)` dedupe and the 3-per-clip cap do not exist yet |
| 5 | Candidate grading | §4.2. Currently a human step. A heuristic (enemy-pixel area near the crosshair) could pre-sort, but **do not ship it as a replacement** without scoring it against hand grades |
| 6 | Three framings | §7. New option, orthogonal to style |
| 7 | End card asset slot | §10. User-supplied clip or image |
| 8 | Verification | §12. Belongs in `tests/verify/` |

### 14.3 Where it does *not* belong

Do not add this as a `plan.py` STYLE — those are clip-cutting pre-roll/tail presets, a
different axis entirely.

---

## 15. Open questions

- **Candidate grading is manual.** Item 5 above. Until that is solved this style cannot run
  unattended; it will happily cut a reel of blank walls.
- **Tempo detection is unproven on other tracks.** The comb in §3.1 was validated on one
  song. Test it on the library in `Videos\AutoStream\songs\` before trusting it.
- **No reference ids.** Every other style carries YouTube ids in `refs`. The reference here
  is a private file, so `refs` is empty and this document is the provenance.
- **Should the negative flip rate follow the framing automatically?** §8.3 ties it to
  full-bleed vs letterboxed, which couples two settings that are otherwise independent.
