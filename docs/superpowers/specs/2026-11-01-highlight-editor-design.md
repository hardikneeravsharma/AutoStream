# The highlight editor -- design

Asked 2026-11-01. The player approved the stream highlight ("the newest valorant
highlight video is good, can be used") and asked for it to open "in a timeline
with editing options other than the song reel edit": which moments to keep, the
facecam area, the facecam zoom, and editing the automatic captions. Before he would
upload it he would change "the moment to keep and remove, the auto generated
captions and the part where the face cam is in focus".

He was shown three directions on the real Bind footage -- A, a list of moments;
B, a timeline with lanes; C, editing by the words -- and chose **"a mix of B and
C"**, then **"go with this flow, and implement it in the application"**.

## What it is

One card on the Clips page, opened from a recording that has a highlight video
("Edit the highlight video"). It edits the video's **cut list**, not its pixels:
nothing is re-rendered while editing, and **Make video** renders the edited cut
list once, beside the original.

- **Preview, top left.** The source recording, played cut to cut the way the video
  will run: removed moments and cut lines skipped, the facecam zoom shown live as
  the same push-in the render makes, the captions drawn over it.
- **Timeline, under the preview.** Lanes for Moments, Facecam zoom, Captions and
  Round ends, with a playhead. A moment is kept or removed with a click, and its
  start and end are trimmed by dragging its edges or nudging them.
- **What you said, on the right.** The transcript, moment by moment, the line
  playing highlighted. Each line can be corrected (that is the caption), hidden
  as a caption, cut out of the video, or marked "face" so the frame zooms on the
  facecam while it is said.
- Both views edit the same project and stay in step; clicking either seeks.
- **The facecam box** can be dragged and resized on the preview; **the zoom**
  is Auto (fit the box) or a fixed amount.
- **Captions** are burned in only when switched on, in English (the translation)
  or as said. An .srt is written beside every edited video either way.

## Decided by the player
- B + C together, in the app, separate from the song-reel Studio.
- Controls: moments kept/removed and trimmed, facecam area, facecam zoom, captions.

## My calls (Claude's), open to change
- Opens from the Clips page, on the recording's summary and on the run's results.
- The project is a JSON file beside the video (`<video>.edit.json`), written by
  the clip job when it renders, and saved as the page edits (debounced). Undo is
  in the page (Ctrl+Z / Ctrl+Shift+Z).
- Make video writes `<video stem>_edited.mp4` and keeps the original; a second
  Make replaces the first edit.
- A cut line or a face line is a flag on the line, applied when the cut list is
  built for the render -- so turning it off restores exactly what was there.
- Captions default to off, English when the player does not speak English.
- One render at a time; refused while a clip job runs, and a clip job refused
  while it renders.

## Second pass (asked 2026-11-01, after using v2.9.1)

"There is no option to edit the time frame of a caption ... how to put a face cam
zoom manually for how much time I want, volume timeline for separate tracks in the
recording, transcription for both audio tracks and keyframe points addition and
overall volume level adjuster just like a video editor". Reference: FilmCraft
(installed; its command set -- caption in/out, split, merge, track keyframes, the
track mixer -- is the model; no source repo was found on the machine).

Decided by the player:
- Caption timing, manual face-zoom spans of any length, a volume line per audio
  track with keyframes, an overall volume, transcripts of both tracks.
- The two tracks are copied out of the recording once (no re-encode, ~130 MB each
  for a 4.6 h stream, beside the edit project) so their volumes can be heard while
  editing: "yes".
- The game track's transcript is for the team-mates' voice comms, and they are
  captioned: "it's my teammates' voice comms I want captioned".

My calls:
- Lines carry `track` ("mic" or "game"). Team captions sit a line above the
  player's and are tinted, so two people talking at once are both readable; the
  .srt prefixes them "[Team]".
- Caption blocks: drag an edge to retime, drag the middle to move; split at the
  playhead, merge with the next, delete, add one at the playhead.
- Face zooms are spans of the recording drawn on the Face zoom lane (drag across
  it), resized by their edges, moved by their middle; they add to the face lines.
- Volume lines are keyframes on the recording's clock in dB, the reel editor's
  rules (`studio.vol_at` / `vol_filter`): straight between points, flat past the
  ends, flat at 0 dB with none. Click the lane to add a point, drag it, double-
  click it away. The render mixes mic and game itself instead of the recording's
  own mix.
- The overall volume moves the loudness target (0 = -16 LUFS), from -10 to +6 dB:
  a plain gain before loudness normalisation would be undone by it.
- Transcribing the game track runs where speech-to-text runs (a graphics card and
  faster-whisper); elsewhere the button says why.

## Not in this version
- Adding footage the planner did not choose (only trimming outward from a cut).
- Reordering moments, music, titles.
- Moving the lower third or the round-result text.
