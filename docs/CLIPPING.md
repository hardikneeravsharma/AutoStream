# Clipping a recording

For someone who installed AutoStream **only to cut clips** — no streaming, no YouTube
account, no OBS. Everything here works on a video you already have, however you
recorded it.

The first-run wizard has a **Just make clips** fork that skips the broadcast setup
entirely. If you took the streaming path by mistake, nothing is lost: the Clips page
does not care.

---

## The one idea

Two things can tell AutoStream where your kills are, and they are not close in quality.

**Reading the screen.** Always available, needs nothing, and is approximate. It watches
the kill feed or a HUD marker frame by frame. Measured against Riot's own record over
two Valorant sessions — 145 minutes, 63 kills — it got 71% of what it reported right and
found 56% of the kills that were there.

**The game's own record.** A Counter-Strike `.dem`, or Valorant's match record. Exact
kill times, exact rounds, and things no camera can see: who was still alive, whether you
were flashed, whether the shot went through smoke. This is what turns "3 kills" into
"1v3 CLUTCH".

Everything below is arranged around making sure the second one is available. When it is,
the screen read is still performed — but only as a fingerprint to work out *where in
your video* the match sits, after which its answers are thrown away and replaced.

---

## Setup, once

**Two tools.** The Clips page installs ffmpeg and Tesseract for you — press the button
when it offers. ffmpeg is needed for everything. **Tesseract is only for Counter-Strike**,
which is the one game whose kill feed has to be read as text; Valorant and Delta Force
need neither it nor any configuration at all.

**Your in-game name — Counter-Strike only.** The feed names the killer first, so your
name is how a kill is told from a death from an assist. Set it on the Clips page. No
other game asks.

**HUD scale.** The read regions were measured at one person's HUD scale. If yours
differs, recalibrate from **Clips → Calibrate a game**. Resolution does not matter — the
regions are proportional — but scale does.

---

## The walkthrough

### 1. Get the game's record while you still can

This is the step with a deadline, and the only one that cannot be done later.

| Game | What to do | Deadline |
|---|---|---|
| **Valorant** | Have AutoStream running any time Valorant is — even just sitting in the menu. It caches your **last 5 matches**. | Once those 5 roll over, that record is gone permanently. |
| **Counter-Strike 2** | Download the replay: **Watch → your match → Download**. | Valve keeps sharing codes for a while; the demo on disk keeps forever. |
| **Delta Force, anything else** | Nothing. There is no record to get. | — |

Valorant's record is read out of the **running Riot client**, not from a server you can
query later. That is the whole reason for the deadline: close the game and the
credentials go with it. It does not matter which tool recorded your video — the record
comes from the game, not the footage — so a ShadowPlay or Medal capture is served just
as well as one AutoStream made itself.

### 2. Hand over the video

**Clips → Clip a video file → Choose video…**, pick the game in the dropdown, then
**Use this video**.

**Do not rename the file.** If it carries an OBS-style stamp — `2026-09-05 00-46-48.mp4`
— that is used as the exact recording time and is how the video is matched to its demo
or match record. Without a stamp, the file's modified time less its duration is used
instead, which is close but not exact.

### 3. Choose the part to clip

A filmstrip of the whole video appears with two handles. Drag them, or click a frame to
start there and shift-click to end there.

**Do not skip this.** A recording is not one game. It holds a menu, a warm-up, the tail
of the previous match and often a different game after it — and the reader handles one
match at a time. On a two-hour file holding half an hour of Counter-Strike, trimming is
the difference between a twenty-minute scan and a three-minute one. A pair of timecodes
could not do this job; you cannot see where one game ends by looking at numbers.

### 4. Pick a style

| Style | Before the kill | After | Length |
|---|---|---|---|
| **Short-form** | 1.5s | 2.0s | 15s |
| **Montage cut** | 1.0s | 1.5s | 6s |
| **Full context** | 6.0s | 4.0s | 30s |

Counter-Strike overrides the two short styles with floors of **3s before and 4s after**,
because it is not a respawn shooter: a kill is the end of a slow approach, and the feed
row announcing it lives a median of five seconds. Cut to the standard 1.5s and the clip
opens with the shot already fired.

Then set the minimum kills, whether you want 1080x1920 verticals, and whether to build a
montage.

### 5. Review before cutting

**Nothing has been encoded yet.** You get the full list of what *would* be cut, and per
clip you can:

- write a **caption** burned onto the vertical
- add a **spoken line** in one of the built-in voices
- set the **framing** for the vertical crop
- add **zoom, freeze and sound** effects, dragged to length directly on the timeline
- **trim** the in and out points

Zoom goes to **4x** and can be aimed at a corner of the frame rather than the centre.

This is the step that costs nothing and saves the most: a clip the reader got wrong is
one click to discard, before you have spent anything encoding it.

### 6. Cut

Masters in 16:9, verticals at 1080x1920 if you asked for them, a montage with
transitions, and a music reel if you supplied a track. Filenames say what is inside:
`VALORANT_03_2kills_19m48s_8s_vertical.mp4`.

Re-cutting the same recording reuses the readings from the first pass, so a second run
with different settings is near-instant.

---

## What each game gives you

### Valorant

Found by the **yellow border** the game draws around your own half of a feed row — left
end means you got the kill, right end means you died. No OCR, no in-game name, nothing
to configure. Assists show as a detached portrait tile and are detected separately, so
they are not clipped as kills.

With the match record it also labels rounds properly: **1v3**, **CLUTCH**, **PLANT**,
**DEFUSE**, **OVERTIME**, and Riot's own ceremony names. Who was alive at each kill is
*counted* from the record, not inferred — the reader could never do that, because being
alive is not something the screen shows.

Scans at about **14x** real time.

### Counter-Strike 2

Best case is the demo, which is found on disk automatically by matching the recording's
time against each replay's own match timestamp.

If none matches, the run **stops and asks** rather than silently spending forty minutes
on a worse answer. You then have three options:

1. **Paste the match sharing code** and press *Download in Counter-Strike*. Wait for the
   download to actually finish before starting the job — a replay still downloading is
   not yet a replay on disk.
2. **Kills only** — reads the card tally under the crosshair. About **10x** real time,
   no OCR and no in-game name needed, and assists cannot leak in. Clips are named by
   kill count.
3. **Full rounds** — reads the scoreboard as well, which is where CLUTCH, PISTOL ROUND
   and the rest come from. About **1.2x** real time, so roughly eight times slower.

The twelve minutes already read while searching are kept, so answering the prompt and
running again goes straight to matching rather than starting over.

### Delta Force

Ships calibrated and needs nothing. The skull under the crosshair is template-matched,
which is far cheaper than reading a feed — a two-hour session scans in about a minute.

### Any other game

**Clips → Calibrate a game**: scrub to a frame just after a kill and drag a box round
the marker. It then measures whether that patch actually stands out from the rest of the
recording, and refuses to save a template that would match everything. About a minute's
work, once.

For a game that draws no kill confirmation at all, pick **Only in the kill feed** and
box the whole feed instead.

---

## When it goes wrong

| What you see | What it means |
|---|---|
| **"Tesseract unavailable"** | Only Counter-Strike needs it. Press install on the Clips page. |
| **Make clips greyed out** | The page says why underneath. Usually a missing tool or an uncalibrated game. |
| **It asks for a sharing code** | No demo on disk matched. Either fetch it, or pick one of the two screen readers. |
| **Clips are 4 seconds long in CS2** | An old profile without the pre-roll floors. Recalibrate. |
| **No kills found** | Usually HUD scale, or a capture overlay sitting on the kill feed at the top right. |
| **Valorant clips miss kills or double up** | No match record was cached for that session, so it fell back to the screen. Nothing can recover it after the fact — see step 1. |
