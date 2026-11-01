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

## Not in this version
- Adding footage the planner did not choose (only trimming outward from a cut).
- Reordering moments, music, titles.
- Moving the lower third or the round-result text.
