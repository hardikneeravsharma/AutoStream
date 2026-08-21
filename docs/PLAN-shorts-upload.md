# Plan — upload clips to YouTube Shorts from the dashboard

## Context

The clipper already produces exactly what Shorts wants and then stops. Every run writes
`vertical/` clips at **1080×1920, H.264/AAC, 5–15 seconds**, captioned and branded — and
they sit on disk until they are dragged into a browser by hand. That last step is the only
manual part of an otherwise automatic pipeline, and it is the step that decides whether any
of it was worth doing.

This adds uploading to the **Clips** page: pick the clips, confirm, watch progress, get the
links back.

---

## What already exists and must be reused

| Need | Already built | Where |
|---|---|---|
| OAuth + credentials | `YouTube.authorise()`, token on disk | `autostream/youtube.py` |
| Quota accounting | `_spend()`, `check_budget()`, `quota_left()` | `youtube.py`, `state.py` |
| Background work off the engine thread | `ClipJob` / `JobRunner` | `clips/jobs.py` |
| Progress to the UI | the `clips` key inside `Server.status()`, polled every 2s | `webui.py`, `ui/clips.py` |
| What was produced | `clips.json` per run: path, kills, caption, tags | `clips/jobs.py` |
| Title templating | `titles.render_title()` and its `{token}` vocabulary | `titles.py` |

**Nothing here needs a new polling mechanism, a new thread model, or a new auth flow.** The
upload job is a second implementation of the same `JobRunner` contract.

---

## Three constraints that shape the design

### 1. Quota is the binding limit, and its cost is currently uncertain

`videos.insert` **historically cost 1600 units** against a 10,000/day default — six uploads a
day. Reporting from December 2025 says Google cut it to ~100 units and moved uploads into a
separate 100-call/day bucket, but sources published since still disagree with each other.

**Do not hard-code either number.** Assume the expensive case, measure the real one, and make
the ceiling a setting:

- `UPLOAD_COST = 1600` as the conservative default, in `youtube.py` beside the other costs.
- A `youtube.upload_daily_max` setting (default **5**) that is enforced *independently* of
  the quota arithmetic, so a wrong cost estimate cannot silently burn the day's quota.
- After the first real upload, log the quota actually consumed. If it turns out to be ~100,
  the constant gets corrected from evidence rather than from a blog post.

A single streaming session already spends 250 (300 with a thumbnail). Six uploads at the old
price would leave nothing for streaming — **uploading must never be able to block a stream.**
`check_budget()` gets a reserve so the streaming path always wins.

### 2. Scope — probably fine, verify rather than assume

`videos.insert` accepts `youtube.upload`, `youtube`, or `youtubepartner`. AutoStream already
requests **`https://www.googleapis.com/auth/youtube`**, which should cover it.

That matters because adding a scope invalidates the stored token and forces the user through
OAuth again. So: **try the upload with the existing token first.** Only if the API returns an
insufficient-scope error do we add `youtube.upload` to `SCOPES` and prompt a re-auth — and
that prompt must explain why.

### 3. What makes a Short a Short

Since October 2024: **vertical or square, three minutes or under, and YouTube classifies it
automatically.** `#Shorts` in the title is not required and should not be added as
superstition. The existing verticals already qualify on both counts, so no re-encoding is
needed — upload the file as it stands.

---

## Design

### Nothing uploads by itself

Recording and clipping are safe to automate because they are local. Publishing is not: it is
public, attributed, and awkward to undo. This follows the same rule as the 20-second cancel
window — **an upload happens because a person pressed a button**, never because a session
ended. There is deliberately no `auto_upload` setting.

### Default privacy is `unlisted`

Matching `youtube.privacy`'s own default and the "first week on unlisted" advice in the
README. A clip goes out unlisted, you watch it back, and you make it public yourself. The
Clips page offers public/unlisted/private per batch, defaulting to whatever the last batch
used.

### The flow

```
Clips page -> a finished run's results
   [x] 01  3 kills  TRIPLE KILL      15s
   [x] 02  2 kills  2K SNIPER        12s
   [ ] 03  1 kill   (no caption)      8s
   ...
   privacy [unlisted v]   title template [{caption} | {game} #{n}]
   [ Upload 2 clips ]   "uses ~3200 of 9700 remaining quota"
```

Selection defaults to **clips that earned a caption** — those are the ones with something to
say. The uncaptioned ones are unticked but available.

### Title and description

Reuse the `titles.py` templating rather than inventing a second one. New tokens available to
a clip: `{caption}`, `{kills}`, `{game}`, `{at}`, `{channel}`, `{date}`, `{n}`.

- Title default: `{caption} — {game}` falling back to `{kills} kills — {game}`.
- Description default: a short line plus the channel, from a setting.
- **Title is hard-capped at 100 characters** and validated before the call, because YouTube
  rejects the whole request otherwise and the failure arrives after the file has uploaded.

### The job

`clips/upload.py`, mirroring `clips/jobs.py`:

```python
class UploadJob:          # same snapshot() contract as ClipJob
    steps = ("check", "upload", "verify")
```

- One job at a time, on `JobRunner` (or a second runner instance, keyed separately so a clip
  cut and an upload cannot fight over the GPU and the network at once).
- **Resumable uploads** — `MediaFileUpload(..., resumable=True, chunksize=4MB)` and
  `next_chunk()` in a loop. A 40 MB clip on a domestic uplink is not instant, and a
  non-resumable upload that fails at 90% has to start over.
- Per-chunk progress into the existing status payload, so the meter moves rather than sitting
  at 0 for a minute.
- Cancellation between chunks, same cooperative flag as `ClipJob`.
- Results written back into the run's `clips.json` as `video_id` and `url`, so the page can
  show links and a re-upload can be recognised as a duplicate.

### Failures that must be handled, not swallowed

| Failure | Behaviour |
|---|---|
| Quota exhausted | Refuse before uploading anything; say how much is left and when it resets |
| Daily cap reached | Refuse, name the setting |
| Insufficient scope | Explain, offer re-auth, do not silently re-prompt |
| File missing | Skip that clip, carry on with the rest, report it |
| Upload fails mid-batch | Keep the successes, report which failed and why |
| Duplicate | Warn if the clip already has a `video_id`; require an explicit re-upload |

---

## Files

| File | Change |
|---|---|
| `autostream/youtube.py` | `upload_video()` with resumable chunks and a progress callback; `UPLOAD_COST`; quota reserve in `check_budget()` |
| `autostream/clips/upload.py` | **new** — `UploadJob`, title/description rendering, per-clip result recording |
| `autostream/clips/jobs.py` | expose a second runner, or key the existing one so cut and upload cannot overlap |
| `autostream/webui.py` | `POST /api/clips/upload`, `POST /api/clips/upload/cancel`; upload state inside `status()` |
| `autostream/ui/clips.py` | selection checkboxes on the results list, privacy select, template field, upload button, progress, links |
| `autostream/ui/css.py` | the results list becomes selectable rows |
| `autostream/cfg.py`, `schema.py` | `youtube.upload_daily_max`, `clips.upload_privacy`, `clips.upload_title`, `clips.upload_description` |
| `tests/test_clips.py` | see below |

---

## Verification

**Unit, no network:**
- title rendering respects the 100-character cap and every token
- an over-long title is rejected *before* the request, not after
- quota maths refuses at the right threshold and leaves the streaming reserve intact
- the daily cap holds independently of the quota estimate
- a missing file is skipped without killing the batch
- `clips.json` round-trips `video_id`/`url`

**Against the real API — one clip, `private`:**
- confirm the existing token is accepted (settles the scope question)
- **log the actual quota consumed** and correct `UPLOAD_COST` from that
- confirm YouTube classifies it as a Short without `#Shorts`
- delete it afterwards

**End to end:** upload two clips unlisted from the dashboard, confirm both links resolve, both
appear in the Shorts feed, and `clips.json` carries the ids.

**Regression:** the full suite (77 tests) must stay green; streaming must be unaffected when
`upload_daily_max` is 0.

---

## Out of scope

- Auto-uploading when a session ends — deliberate, see above
- Scheduling or drip-feeding uploads
- Editing titles per clip in the UI beyond the template (the template plus the caption is
  enough; per-clip editing is a text editor's job)
- Playlists, end screens, cards
- Any other platform

## Open question for the user

**Whether to upload the montage and promo reels too.** They are 2–4 minutes, so a montage
often exceeds the 3-minute Shorts ceiling and would land as a normal video instead. That is a
different thing with different expectations, and worth deciding rather than assuming.
