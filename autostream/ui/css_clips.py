"""The Clips page's part of the 2026-10-29 redesign: the recordings beside a
summary of what will happen to the one picked (screen A), and the moments a
scan found laid along the recording, to untick before cutting (screen B).

Appended to the end of css.py (see the last lines there), so these rules win
over the older Clips block without that block being rewritten. The step
screens behind each Change keep their layout and only pick up the tokens.
Tokens only: no colour, radius or shadow is written here as a number of its
own.
"""
from __future__ import annotations

CLIPS_CSS = r"""
/* ==========================================================================
   CLIPS, 2026-10-29: a summary to start, a timeline of moments to cut from
   ========================================================================== */

/* ---- screen A: the recordings, and the summary beside them --------------- */
.clip-a{
  display:grid;
  grid-template-columns:minmax(280px,360px) minmax(0,1fr);
  gap:var(--space-8);
  align-items:start;
}
/* Nothing listed and nothing picked: the empty state takes the whole width. */
.clip-a.is-solo{grid-template-columns:minmax(0,1fr)}
.clip-a.is-solo .clip-sum{display:none}
.clip-a-list{display:flex;flex-direction:column;gap:var(--space-5);min-width:0}

/* A video from elsewhere: one quiet dashed box above the list. */
.clip-local{
  display:flex;flex-direction:column;gap:var(--space-4);
  padding:var(--space-5);
  border:var(--border-hair) dashed var(--border-strong);
  border-radius:var(--radius-md);
  color:var(--text-secondary);
}
.clip-local-row{display:flex;align-items:center;gap:var(--space-4)}
.clip-local-row>.icon{flex:0 0 auto;width:var(--size-icon);height:var(--size-icon);opacity:var(--opacity-ghost)}
.clip-local-lead{flex:1 1 auto;min-width:0;font-size:var(--text-sm)}
.clip-local .localclip{gap:var(--space-4);align-items:center}
.clip-local .localclip>.select{flex:1 1 140px;min-width:0;height:var(--h-control-sm)}
.clip-local .localclip-path{font-size:var(--text-xs)}
.clip-local .localclip-path:empty{display:none}

/* The list's own bar: a count, the game filter, refresh. Not sticky here --
   the list is short, and a bar that floats over the summary column beside it
   would cover the steps. */
.clip-a-bar{
  position:static;margin:0;padding:0;background:none;
  display:flex;align-items:center;gap:var(--space-4);
}
.clip-a-count{flex:1 1 auto;min-width:0;color:var(--text-secondary);font-size:var(--text-sm);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.clip-a-bar .select{width:auto;max-width:12rem;height:var(--h-control-sm)}

.clip-listwrap{
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  background:var(--surface);
  overflow:hidden;
}
/* The day headings the list is grouped by. Sentence case, quiet, with the
   count at the end; they are labels, not rows, and are not focusable. */
.clip-day{
  display:flex;align-items:center;gap:var(--space-4);
  padding:var(--space-5) var(--space-5) var(--space-3);
  font-size:var(--text-xs);font-weight:600;color:var(--text-secondary);
}
.clip-day-n{color:var(--text-tertiary);font-weight:500;font-variant-numeric:tabular-nums}
.clip-list>.clip-day+.clip-row{border-top:0}
.clip-list>.clip-day:not(:first-child){border-top:var(--border-hair) solid var(--border-subtle)}

.clip-row{
  grid-template-columns:16px minmax(0,1fr) auto;
  align-items:start;
  gap:var(--space-4);
  padding:var(--space-4) var(--space-5);
}
.clip-row-mark{display:flex;padding-top:var(--space-1)}
.clip-row-name{font-weight:500}
.clip-row-sub{
  font-size:var(--text-xs);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.clip-row-when{font-variant-numeric:tabular-nums;padding-top:var(--space-1)}
/* Selected is a tone, not an accent bar: the accent is kept for the primary
   button, the sidebar and the focus ring. */
.clip-row.is-active{box-shadow:none;background:var(--surface-active)}
.clip-row:focus-visible{box-shadow:inset 0 0 0 var(--focus-ring-width) var(--accent)}

.clip-a-empty{
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  background:var(--surface);
  padding:var(--space-10) var(--space-8);
}
.clip-a-empty #clip-empty-head{margin:0;font-size:var(--text-md);font-weight:600;color:var(--text-primary)}
.clip-a-empty #clip-empty-sub{margin:0;max-width:56ch;line-height:1.5}

/* The summary. */
.clip-sum{display:flex;flex-direction:column;gap:var(--space-6);min-width:0}
.clip-sum-none{
  display:flex;align-items:center;justify-content:center;
  min-height:240px;padding:var(--space-8);
  border:var(--border-hair) dashed var(--border-subtle);
  border-radius:var(--radius-md);
  color:var(--text-tertiary);text-align:center;
}
.clip-sum-none p{margin:0}
.clip-sum-head p{margin:var(--space-2) 0 0}
.clip-sum-title{
  margin:0;font-size:var(--text-lg);font-weight:600;line-height:1.25;letter-spacing:-.015em;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}

/* The filmstrip, with the part to clip outlined on it. */
.clip-sum-strip{
  position:relative;
  display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:var(--space-1);
  width:100%;padding:0;margin:0;
  border:0;border-radius:var(--radius-sm);overflow:hidden;
  background:var(--surface-sunken);cursor:pointer;
}
.clip-sum-strip img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;
  background:var(--surface-raised);opacity:.6}
.clip-sum-window{
  position:absolute;top:0;bottom:0;
  border-radius:var(--radius-xs);
  box-shadow:inset 0 0 0 2px var(--text-primary);
  pointer-events:none;
}
.clip-sum-strip:hover img{opacity:.75}

.clip-sum-steps{
  list-style:none;margin:0;padding:0;
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  background:var(--surface);
}
.clip-sum-step{
  display:grid;
  grid-template-columns:22px minmax(7rem,9.5rem) minmax(0,1fr) auto;
  align-items:center;
  gap:var(--space-5);
  min-height:var(--h-row-list);
  padding:var(--space-3) var(--space-5);
}
.clip-sum-step+.clip-sum-step{border-top:var(--border-hair) solid var(--border-subtle)}
.clip-sum-num{
  display:inline-grid;place-items:center;width:20px;height:20px;
  border-radius:50%;
  box-shadow:inset 0 0 0 1px var(--border-strong);
  font-size:var(--text-xs);font-weight:600;color:var(--text-secondary);
  font-variant-numeric:tabular-nums;
}
.clip-sum-label{color:var(--text-secondary)}
.clip-sum-val{min-width:0;overflow-wrap:anywhere}
.clip-sum-step.is-warn .clip-sum-val{color:var(--warn)}
.clip-sum-step.is-warn .clip-sum-num{box-shadow:inset 0 0 0 1.5px var(--warn);color:var(--warn)}

.clip-sum-go{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-4)}
.clip-sum-why{margin:0;font-size:var(--text-sm);line-height:1.5;max-width:70ch}
.clip-sum-why.is-warn{color:var(--warn)}

/* The run's progress sits above the stages; give it room to breathe there. */
#clip-progress{margin-bottom:var(--space-6)}

/* ---- screen B: the moments ---------------------------------------------- */
.clip-mom{display:block}
.clip-moments{display:flex;flex-direction:column;gap:var(--space-5)}
.clip-mom-head{
  display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;
  gap:var(--space-5);
}
.clip-mom-titles{min-width:0;flex:1 1 16rem}
.clip-mom-titles p{margin:var(--space-2) 0 0}
.clip-mom-title{
  margin:0;font-size:var(--text-lg);font-weight:600;line-height:1.25;letter-spacing:-.015em;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.clip-mom-acts{flex-wrap:wrap;justify-content:flex-end}

/* The timeline: the recording end to end, matches as bars across the top,
   each moment a tick standing on the bottom, taller for more kills. */
.clip-tl{
  position:relative;
  height:96px;
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  background:var(--surface-sunken);
  overflow:hidden;
  user-select:none;
  touch-action:none;
}
.clip-tl.is-review{cursor:crosshair}
.clip-tl-bars,.clip-tl-ticks{position:absolute;left:var(--space-4);right:var(--space-4)}
.clip-tl-bars{top:0;bottom:0}
.clip-tl-ticks{bottom:var(--space-5);height:48px}
.clip-tl-bar{
  position:absolute;top:var(--space-4);height:20px;
  padding:0 var(--space-4);
  border-radius:var(--radius-xs);
  background:var(--surface-active);
  color:var(--text-secondary);font-size:var(--text-xs);line-height:20px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.clip-tl-part{
  position:absolute;top:0;bottom:0;
  border-inline:var(--border-hair) dashed var(--border-strong);
}
.clip-tl-tick{
  position:absolute;bottom:0;
  width:3px;margin-left:-1px;
  height:calc(var(--space-4) + var(--h, 1) * var(--space-4));
  border-radius:1px;
  background:var(--text-primary);
}
.clip-tl-tick.is-off{background:var(--text-tertiary);opacity:.45}
/* An earlier run's kills, under the clips it cut: small and quiet. */
.clip-tl-kill{
  position:absolute;bottom:var(--space-5);
  width:2px;height:var(--space-4);margin-left:-1px;
  background:var(--text-tertiary);opacity:.7;
}

/* The voice and montage choices above the rows: one quiet line each. */
#clip-review-bulk{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-5)}
#clip-review-bulk .field-label,
.clip-review-field>.field-label{font-size:var(--text-sm);font-weight:500;color:var(--text-secondary)}
#clip-review-bulk .field-inline{gap:var(--space-4)}
#clip-review-bulk .muted{font-size:var(--text-xs)}
.clip-tl-drag{
  position:absolute;top:0;bottom:0;
  background:var(--surface-active);opacity:.6;
  box-shadow:inset 0 0 0 1px var(--border-strong);
  pointer-events:none;
}
.clip-tl-axis{
  display:flex;justify-content:space-between;
  margin-top:calc(var(--space-3) * -1);
  padding:0 var(--space-4);
  color:var(--text-tertiary);font-size:var(--text-xs);font-variant-numeric:tabular-nums;
}

.clip-mom-sum{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--space-4)}
.clip-mom-count{font-size:var(--text-md);font-weight:600}
.clip-mom-body{display:flex;flex-direction:column;gap:var(--space-5)}

/* The rows: a tick, a still, what it is, its kills as dots, where it is. */
.clip-mom .clip-review-list{
  gap:0;
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  background:var(--surface);
  overflow:hidden;
}
.clip-mom .clip-review-list:empty{display:none}
.clip-mom-row{
  display:grid;
  grid-template-columns:16px 72px minmax(0,1fr) 64px 64px auto;
  align-items:center;
  gap:var(--space-5);
  min-height:52px;
  padding:var(--space-3) var(--space-5);
}
.clip-mom-row+.clip-mom-row{border-top:var(--border-hair) solid var(--border-subtle)}
.clip-mom-tick{width:16px;height:16px;margin:0;accent-color:var(--text-primary);cursor:pointer}
.clip-mom-thumb{
  display:block;width:72px;aspect-ratio:16/9;object-fit:cover;
  border-radius:var(--radius-xs);background:var(--surface-raised);
}
.clip-mom-main{display:flex;flex-direction:column;gap:var(--space-1);min-width:0}
.clip-mom-name{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.clip-mom-sub{font-size:var(--text-xs);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.clip-mom-at{text-align:end;color:var(--text-secondary);font-variant-numeric:tabular-nums}
.clip-mom-row.is-off .clip-mom-thumb,
.clip-mom-row.is-off .clip-mom-main,
.clip-mom-row.is-off .clip-pips,
.clip-mom-row.is-off .clip-mom-at{opacity:.45}
.clip-mom-more{grid-column:2/-1;padding:var(--space-3) 0 var(--space-2)}
.clip-mom-none{padding:var(--space-8);text-align:center}
.clip-mom-none p{margin:0 0 var(--space-2)}

.clip-pips{display:inline-flex;align-items:center;gap:3px}
.clip-pips i{width:6px;height:6px;border-radius:50%;background:var(--text-secondary)}

/* ---- the step screens behind Change: tokens only ------------------------ */
/* The rail's ticks and its "you are here" use the text colours rather than the
   accent, which the redesign keeps for four places only. */
.clip-rail-step.is-done .clip-rail-dot{background:var(--text-secondary);color:var(--surface)}
.clip-rail-step.is-now button,
.clip-rail-step.is-here button{border-color:var(--border-strong);box-shadow:none}
.clip-rail-step button{border-radius:var(--radius-pill)}
.clip-review-row,.clip-made-row{border-color:var(--border-subtle)}
.clip-stepnav{border-top-color:var(--border-subtle)}
/* The song edit on the results: a plain primary button now, not a pulsing
   one. The calm the redesign is after does not survive one shimmering
   control, and the button is just as easy to find standing still. */
.btn-flashy{animation:none}
.btn-flashy::after{display:none}

/* ---- the reel maker on this page (ui/reel.py): tokens only -------------- */
.reel-h{display:flex;align-items:center;gap:var(--space-4);
  font-size:var(--text-sm);font-weight:600;color:var(--text-primary)}
.reel-h-n{
  display:inline-grid;place-items:center;width:20px;height:20px;flex:0 0 auto;
  border-radius:50%;box-shadow:inset 0 0 0 1px var(--border-strong);
  font-size:var(--text-xs);font-weight:600;color:var(--text-secondary);
  font-variant-numeric:tabular-nums;
}
.reel-step-chip{border-radius:var(--radius-pill);font-size:var(--text-xs)}
.reel-step-chip.is-done{border-color:var(--border-strong)}
.reel-clock{font-size:var(--text-lg)}

/* ---- narrow windows ------------------------------------------------------ */
@media (max-width:1000px){
  .clip-a{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:880px){
  .clip-row{grid-template-columns:16px minmax(0,1fr)}
  .clip-sum-step{grid-template-columns:22px minmax(0,1fr) auto}
  .clip-sum-label{grid-column:2}
  .clip-sum-val{grid-column:2}
  .clip-sum-step>.clip-sum-change,.clip-sum-step>span:last-child{grid-column:3;grid-row:1 / span 2}
  .clip-sum-strip{grid-template-columns:repeat(6,minmax(0,1fr))}
  .clip-sum-strip img:nth-child(even){display:none}
  .clip-mom-row{grid-template-columns:16px minmax(0,1fr) auto auto}
  .clip-mom-row .clip-mom-thumb,.clip-mom-row .clip-pips{display:none}
  .clip-mom-row.is-made{grid-template-columns:14px minmax(0,1fr) auto auto}
  .clip-mom-more{grid-column:1/-1}
}
"""
