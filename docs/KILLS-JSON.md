# kills.json

Every clip job writes `kills.json` into its run folder
(`Videos\AutoStream\clips\<date>_<time>_<Game>\`): every kill the job found, one entry
each, for other tools to find a recording's highlight moments without re-reading it.

It is an **output, not state**. `session.json` beside it is the planner's own memory of
the run -- what a re-cut reads back -- and its content is unchanged by this file. Nothing
in AutoStream reads `kills.json`; deleting it costs nothing but the file. Written by
[`autostream/clips/killslog.py`](../autostream/clips/killslog.py). Issue #275.

**Check `schema_version` first.** This page describes version 1. A field may be *added*
without a bump; a field that is renamed, removed or changes meaning bumps it, and a
reader that does not know the version should stop rather than guess.

## Example

```json
{
  "schema_version": 1,
  "kind": "clips",
  "status": "ok",
  "source": "C:\\Users\\<you>\\Videos\\AutoStream\\2026-10-30 14-05-09.mp4",
  "duration": 2731.5,
  "game": "VALORANT",
  "game_key": "valorant-win64-shipping.exe",
  "started_at": "2026-10-30T14:05:09+05:30",
  "autostream": {"version": "2.3.0", "commit": null},
  "scanned": null,
  "events": [
    {"kind": "kill", "time": 1214.7, "end": 1214.7, "headshot": true, "round": null,
     "source": "screen", "confidence": 0.857, "seen": 7, "burst_id": 0, "burst_size": 2},
    {"kind": "kill", "time": 1218.2, "end": 1218.2, "headshot": false, "round": null,
     "source": "emblem", "confidence": 0.8, "seen": 5, "burst_id": 0, "burst_size": 2},
    {"kind": "kill", "time": 2087.6, "end": 2087.6, "headshot": true, "round": 7,
     "source": "record", "confidence": 1.0, "seen": null, "burst_id": 1, "burst_size": 1}
  ]
}
```

## Top level

| Field | Meaning |
|---|---|
| `schema_version` | `1`. Check it before reading anything else. |
| `kind` | What sort of run wrote it. `clips`: a full run, clips cut. `plan_only`: the kills were found and the clips planned, nothing cut. `match-videos`: a Marvel Rivals run that makes match videos (`mode: summary`) -- its events are KOs, see below. |
| `status` | `ok`, or `no_kills` when the run found nothing. A `no_kills` file has `"events": []`; it exists so "found nothing" can be told apart from "never ran". |
| `source` | The recording's path, as the job opened it. |
| `duration` | The recording's length in seconds. |
| `game` | The game's display name. |
| `game_key` | The game's executable key (as in `games.yaml`), or `null` when the job was not given one. |
| `started_at` | When the **job** started (not the recording), local time with its UTC offset, to the second. |
| `autostream.version` | The AutoStream version that wrote it. |
| `autostream.commit` | Short git commit, when running from a source checkout; `null` in a packaged build. |
| `scanned` | `[start, end]` in recording seconds when only part of the recording was read (a chosen window or chosen matches); `null` when the whole recording was. Times outside it were not looked at, so the absence of a kill there means nothing. |
| `events` | The kills, sorted by `time`. |

## Each event

| Field | Meaning |
|---|---|
| `kind` | `"kill"`. Always, in version 1; deaths and assists may be added later as other kinds without a bump, so a reader should skip kinds it does not know. |
| `time` | When the kill happened, seconds into the recording, 3 dp. |
| `end` | When the reading of it ended (the kill-feed row leaving the screen, say), 3 dp. Never before `time`; equal to it when nothing longer was measured. |
| `headshot` | `true` / `false` where the job measured it (Valorant's kill-feed check); `null` where it did not. `null` is "unknown", not "no". |
| `round` | The round number, 1-based, when the run knew rounds (a match record, a Counter-Strike demo, a round read); otherwise `null`. |
| `source` | Where the kill came from, by precedence: `record` (the game's own match record, or a demo -- nothing read off the screen), else `emblem` (the kill emblem on screen placed or confirmed it), else `screen` (a reader of the HUD or kill feed). |
| `confidence` | See below. A number in `[0, 1]`, or `null`. |
| `seen` | How many frames the reader saw this kill in, when it counted; otherwise `null`. |
| `burst_id` | Which fight it belongs to: the 0-based index, in time order, of its burst. |
| `burst_size` | How many kills are in that burst. |

### `confidence`

How much the *reading* can be trusted -- not how good a clip it would make.

- **`1.0`** for a `record` kill: the game said so.
- **The share of sightings that said "kill"**, 3 dp, where the reader voted frame by
  frame. The Valorant feed reader classifies a row in every frame it is on (kill, death,
  assist, other); a row seen 7 times and called a kill 6 times is `0.857`. A kill the
  emblem moved onto its own time keeps the votes of the screen reading it confirmed.
- **`null`** when nothing was measured: readers that do not vote (the Counter-Strike
  kill feed and card tally, the generic kill-marker match, the loudness reader), kills
  the emblem found on its own, kills Valorant's OCR second look recovered (confirmed by
  at least two readings of the name, which `seen` counts, but not voted on), and kills
  a re-cut reused from an older `session.json`, which never stored the votes.

The planner's `score` is deliberately **not** used here. It is a ranking weight whose
meaning differs per reader, not a probability.

### `burst_id` and `burst_size`

These come from the planner's own clustering (`plan.cluster`, `CLUSTER_GAP` = 22 s): a
kill within 22 s of the previous kill joins that kill's burst, so one long fight can run
well past 22 s from its first kill. They are the fights the planner itself saw, before
it chose windows, so a burst is not the same thing as a clip: clips may split one, drop
it, or be named for a different count.

## When it is written

| Run | Written? |
|---|---|
| Full run (`kind: clips`) | Yes, once the run finishes. |
| Plan only (`kind: plan_only`) | Yes -- and it is the only thing a plan-only run leaves in its folder. |
| Match videos (`kind: match-videos`) | Yes. Events are the match's **KOs** (`time` = `end`, no headshot, round, confidence or seen). |
| Found no kills | Yes, `status: no_kills`, `events: []`. Again the only file in the folder. |
| Failed or cancelled | No. A file there is always from a run that finished. |

Written again, it replaces the old file whole (an atomic write, so a reader never sees
half of one). Writing it never fails the job: if the file
cannot be written, the log says so and the run carries on as if it had been.

**A folder holding only `kills.json` is not a run.** Plan-only and no-kills runs used to
leave no folder at all, and the next run of the same stream and style took that folder's
name. It still does: a run that would land in a folder holding nothing but a `kills.json`
takes the folder, removes the old file before it starts, and writes its own at the end.
The Studio and the stream list never see such a folder, since they look for `clips.json`
and `session.json`.

**Where `source` and `confidence` come from, per game.** Valorant's feed reader votes
frame by frame, so its kills carry `seen` and a confidence; Riot's record and a
Counter-Strike demo are `record` at `1.0`. Kills a re-cut reuses from an older
`session.json` are labelled by what this run could still confirm -- a demo that aligns
again makes them `record`; otherwise they are `screen` with `confidence: null`.
