"""Settings and first-run setup, in the redesign's look (Task 14).

Appended to the end of css.py, so these rules win over the older settings
(section 12) and setup (section 14) blocks without those being rewritten in
place while other pages' agents edit the same file.

Settings follows the approved sample "A. Grouped sections": a short list of
sections under four headings on the left, and on the right each setting as
its label, its explanation and its control -- no plate around a section,
hairlines between rows. The wizard keeps its flow and gains the same type,
spacing and a named step list.
"""

SETTINGS_CSS = """
/* ==========================================================================
   SETTINGS, GROUPED (css_settings.py)
   ========================================================================== */
#view-settings.is-active{max-width:calc(960px + var(--gutter) * 2)}
.settings-body{max-width:none;gap:var(--space-8)}

/* ---- the search, in the top bar ---- */
.set-topsearch{display:flex;align-items:center;min-width:0}
.set-topsearch .input{width:260px;max-width:100%;height:var(--h-control-sm)}
.settings-search-count{margin:0;color:var(--text-secondary);font-size:var(--text-sm)}
.settings-search-count:empty{display:none}

/* ---- the nav: a strip below 1000px, a column with headings above ---- */
.set-nav-group{display:contents}
.set-nav-head{display:none}
.settings-nav-item{
  height:var(--h-control-sm);
  padding:0 var(--space-4);
  font-size:var(--text-sm);font-weight:500;letter-spacing:0;
  color:var(--text-secondary);
}
.settings-nav-item.is-active{background:var(--surface-active);color:var(--text-primary)}
@media (min-width:1000px){
  .settings-layout{grid-template-columns:minmax(0,200px) minmax(0,1fr);gap:var(--space-9)}
  .settings-nav{gap:var(--space-1)}
  .set-nav-group{display:flex;flex-direction:column;gap:var(--space-1)}
  .set-nav-group+.set-nav-group{margin-top:var(--space-5)}
  .set-nav-head{
    display:block;
    padding:0 var(--space-4) var(--space-2);
    font-size:var(--text-xs);font-weight:500;line-height:1.5;
    color:var(--text-tertiary);
  }
  .settings-nav-item{width:100%;justify-content:flex-start}
}

/* ---- a section: a heading, a sentence, then its rows ---- */
.settings-section{
  gap:var(--space-5);
  padding:0;
  background:transparent;
  border:0;
  border-radius:0;
}
/* While searching, each section's heading stays pinned over its results; the
   plate is the page's own colour so it reads as the heading, not a box. */
.settings-section.is-hit .settings-section-head{background:var(--surface);padding-block:var(--space-4)}
.settings-section.is-hit+.settings-section.is-hit{margin-top:var(--space-6)}
.set-sec-title{margin:0;font-size:var(--text-lg);font-weight:600;line-height:1.3;letter-spacing:-.02em;color:var(--text-primary)}
.set-sec-blurb{margin:0;font-size:var(--text-sm);line-height:1.5;color:var(--text-secondary);max-width:64ch}
.set-sec-body{display:flex;flex-direction:column;min-width:0}
.set-sec-acts{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-4);margin-top:var(--space-5)}

/* ---- one setting: words on the left, the control on the right ---- */
.set-sec-body>.field,.set-sec-body details .field{gap:0}
.set-row{
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(0,auto);
  gap:var(--space-8);
  align-items:center;
  padding-block:var(--space-5);
  border-bottom:var(--border-hair) solid var(--border-subtle);
}
.set-row>*{min-width:0}
.set-row-wide{grid-template-columns:minmax(0,1fr);gap:var(--space-4)}
.set-row-text{display:flex;flex-direction:column;gap:var(--space-2);min-width:0}
.set-row-head{display:flex;align-items:baseline;flex-wrap:wrap;gap:var(--space-2) var(--space-4)}
.set-row .field-label{font-size:var(--text-sm);font-weight:500;line-height:1.5}
.set-row .field-help{font-size:var(--text-sm);line-height:1.5;color:var(--text-tertiary);max-width:60ch;margin:0}
.set-row .field-help b{color:var(--text-secondary);font-weight:600}
.set-row .field-key{font-size:var(--text-xs);color:var(--text-tertiary)}
.set-row .field-error{margin:0}
.set-flag{font-size:var(--text-xs);font-weight:500;color:var(--text-tertiary)}
.set-row-control{display:flex;justify-content:flex-end;min-width:0}
.set-row-control>.select,.set-row-control>.input{width:240px;max-width:100%}
.set-row-control>.field-inline{justify-content:flex-end;flex-wrap:nowrap}
.set-row-control>.field-inline>.input,.set-row-control>.field-inline>.select{flex:0 1 200px;width:200px}
.set-row-control>.field-inline>input[type=time]{flex:0 0 auto;width:auto}
.set-row-wide .set-row-control{justify-content:stretch}
.set-row-wide .set-row-control>*{width:100%}

/* The sign-in panel and the folds sit among the rows, so they lose the
   plate too: one hairline above, like a row. */
.set-sec-body>.panel{
  padding:var(--space-5) 0;
  background:transparent;
  border:0;
  border-bottom:var(--border-hair) solid var(--border-subtle);
  border-radius:0;
  display:flex;flex-direction:column;gap:var(--space-4);
}
.set-sec-body>.panel .field-label{font-size:var(--text-sm);font-weight:500}
.settings-body .set-sec-body details{border-top:0;padding-top:var(--space-4)}
.settings-body .set-sec-body details>summary{height:var(--h-row-nav);cursor:pointer}
.settings-body .set-sec-body details>summary .field-label{font-size:var(--text-sm);font-weight:500;color:var(--text-secondary)}
.settings-body .set-sec-body details>summary:hover .field-label{color:var(--text-primary)}
.settings-only-note{margin:var(--space-4) 0 0}

/* ---- Shortcuts ---- */
.set-keys{display:flex;flex-direction:column;gap:var(--space-2);padding-top:var(--space-6)}
.set-keys:first-child{padding-top:var(--space-2)}
.set-keys-title{margin:0;font-size:var(--text-sm);font-weight:600;color:var(--text-primary)}
.set-keys>.field-help{margin:0;color:var(--text-tertiary)}
.set-keys-list{list-style:none;margin:var(--space-2) 0 0;padding:0}
.set-keys-row{
  display:flex;align-items:center;justify-content:space-between;gap:var(--space-6);
  min-height:var(--h-row-nav);
  padding-block:var(--space-2);
  border-bottom:var(--border-hair) solid var(--border-subtle);
  font-size:var(--text-sm);
}
.set-keys-what{min-width:0;color:var(--text-secondary)}
.set-keys-caps{display:flex;align-items:center;gap:var(--space-3);flex:0 0 auto}
.set-keys-or{font-size:var(--text-xs);color:var(--text-tertiary)}

/* ---- the version and report cards, quieter ---- */
.settings-body>.set-about{background:transparent;box-shadow:none}

/* ---- narrow: the words above the control ---- */
@media (max-width:719px){
  .set-row{grid-template-columns:minmax(0,1fr);gap:var(--space-4)}
  .set-row-control{justify-content:flex-start}
  .set-row-control>.select,.set-row-control>.input{width:100%}
  .set-row-control>.field-inline{justify-content:flex-start;flex-wrap:wrap;width:100%}
  .set-row-control>.field-inline>.input,.set-row-control>.field-inline>.select{flex:1 1 160px;width:auto}
  .set-topsearch .input{width:160px}
  .set-keys-row{flex-wrap:wrap}
  /* A switch still fits beside the words, and a switch on a line of its own
     reads as belonging to the row below. */
  .set-row:has(.switch){grid-template-columns:minmax(0,1fr) auto}
  .set-row:has(.switch) .set-row-control{justify-content:flex-end}
}

/* ==========================================================================
   FIRST-RUN SETUP, RESTYLED (css_settings.py)
   ========================================================================== */
#setup-root h1,#setup-root .card-title{
  font-family:var(--font-text);
  font-size:var(--text-lg);font-weight:600;line-height:1.3;letter-spacing:-.02em;
}
#setup-root p{font-size:var(--text-sm);line-height:1.5}
#setup-root .card{box-shadow:none}
#setup-root .card-sub{font-size:var(--text-sm);line-height:1.5;color:var(--text-secondary)}
#setup-root button{font-size:var(--text-sm);font-weight:500;height:var(--h-control)}
#setup-root input:not([type=checkbox]):not([type=radio]),
#setup-root select{height:var(--h-control);font-size:var(--text-sm)}
#setup-root .field-label{font-size:var(--text-sm);font-weight:500}
#setup-root .field-help{font-size:var(--text-xs)}
#setup-root .note{font-size:var(--text-sm);padding:var(--space-4) var(--space-5);background:var(--surface-raised)}
#setup-root .note.warn{background:var(--warn-muted)}
#setup-root .note.bad{background:var(--danger-muted)}
#setup-root .note.ok{background:var(--ok-muted)}
#setup-root .pick-title{font-size:var(--text-md);font-weight:600}
#setup-root .pick-sub{font-size:var(--text-sm)}
#setup-root .pick-meta{font-size:var(--text-xs)}
#setup-root .pick-tag{font-size:var(--text-xs);font-weight:500;padding:0 var(--space-3)}
#setup-root button.pick{border-radius:var(--radius-md);padding:var(--space-6)}
#setup-root fieldset.setup-group{margin:0 0 var(--space-6);padding:0;border:0;min-width:0}
#setup-root fieldset.setup-group>legend{padding:0;margin-bottom:var(--space-3)}

/* The steps by name. Shown when the window is wide enough to hold them on
   one line; below that the thin bar stands in for them, and whichever is on
   screen is the one a screen reader hears. */
.setup-steps{
  display:none;
  list-style:none;margin:0 0 var(--space-8);padding:0;
  flex-wrap:wrap;gap:var(--space-2) var(--space-5);
  font-size:var(--text-xs);color:var(--text-tertiary);
}
.setup-steps:empty{display:none!important}
.setup-step{display:inline-flex;align-items:center;gap:var(--space-3);white-space:nowrap}
.setup-step::before{
  content:"";width:6px;height:6px;border-radius:var(--radius-pill);
  border:var(--border-hair) solid var(--border-strong);
}
.setup-step.is-done{color:var(--text-secondary)}
.setup-step.is-done::before{background:var(--ok);border-color:var(--ok)}
.setup-step[aria-current="step"]{color:var(--text-primary);font-weight:600}
.setup-step[aria-current="step"]::before{background:var(--text-primary);border-color:var(--text-primary)}
@media (min-width:720px){
  .setup-steps{display:flex}
  #setup-stepbar{display:none}
  /* The list already names the step; the line above it keeps the count. */
  #setup-stepname{display:none}
  /* Two equal halves, inputs on one baseline even when a label wraps. */
  #setup-root .field-row{
    grid-template-columns:repeat(2,minmax(0,1fr));
    align-items:end;
    border-top:0;
    padding-block:0;
    margin-bottom:var(--space-5);
  }
}
"""
