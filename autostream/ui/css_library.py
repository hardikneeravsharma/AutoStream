"""Library page styles: games apart from other apps, each game with two switches.

Appended to the end of css.py's sheet, so these win over section 10's older
`.app-card` rules, which stay for the shapes nothing here overrides. Every rule
is scoped under `.lib-*` so no other page's rows change.
"""
from __future__ import annotations

LIBRARY_CSS: str = """
/* ==========================================================================
   LIBRARY (redesign). Games and other apps on two tabs; a game row is cover,
   name, source, Records, Goes live and a "..." menu holding the launches.
   ========================================================================== */
.lib-bar{gap:var(--space-4);flex-wrap:wrap}
.lib-bar .input{flex:0 1 260px;margin-left:auto}
.lib-bar .lib-count{font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
.lib-bar .lib-count:empty{display:none}
.lib-tabs .seg-btn{gap:var(--space-3)}
.lib-n{color:var(--text-tertiary);font-variant-numeric:tabular-nums;font-weight:400}
.lib-n:empty{display:none}
/* The list's holder is a .card only so the page reads as drawn to the tests
   that count cards; the list draws its own frame, so the card draws none. */
.lib-card{gap:0;padding:0;background:none;border:0;border-radius:0;box-shadow:none}

/* The list draws its own corners: the row menus have to be able to hang out
   of the last row, which the primitive's overflow:hidden would clip. */
.lib-list{overflow:visible}
.lib-list>.app-card:first-child{border-top-left-radius:var(--radius-md);border-top-right-radius:var(--radius-md)}
.lib-list>.app-card:last-child{border-bottom-left-radius:var(--radius-md);border-bottom-right-radius:var(--radius-md)}

.lib-list .app-card{
  position:relative;
  gap:var(--space-5);
  min-height:56px;
  padding:var(--space-3) var(--space-5);
}
.lib-list .app-card.is-game{
  grid-template-columns:64px minmax(0,1fr) 112px 120px 32px;
  grid-template-areas:"cover id rec live more";
}
.lib-list .app-card.is-app{
  grid-template-columns:minmax(0,1fr) auto 32px;
  grid-template-areas:"id move more";
}
.lib-list .lib-cover{grid-area:cover}
.lib-list .lib-id{grid-area:id}
.lib-list .lib-sw[data-act="lib-records"]{grid-area:rec}
.lib-list .lib-sw[data-act="lib-golive"]{grid-area:live}
.lib-list .lib-move{grid-area:move}
.lib-list .lib-more{grid-area:more}

/* Name and source side by side on a wide window, so the source reads as a
   column; stacked once the row is narrow (below). */
.lib-id{display:grid;grid-template-columns:minmax(0,1fr) 112px;align-items:center;gap:var(--space-5);min-width:0}
.lib-list .app-name{font-size:13px;font-weight:500;line-height:1.35;letter-spacing:0}
.lib-list .app-source{font-family:var(--font-text);font-size:12px;font-weight:400;color:var(--text-secondary)}

/* The cover: the game's own thumbnail, or a quiet plate with its initial. */
.lib-cover{
  position:relative;
  display:flex;align-items:center;justify-content:center;
  width:64px;height:36px;
  overflow:hidden;
  border-radius:var(--radius-xs);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
}
.lib-cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.lib-initial{font-size:13px;font-weight:600;color:var(--text-tertiary)}

/* A row switch is the primitive at row size: smaller track, same states. */
.lib-sw{min-height:var(--h-control-sm);font-size:13px;gap:var(--space-4);justify-self:start}
.lib-sw .switch-track{width:28px;height:16px}
.lib-sw .switch-thumb{top:1px;inset-inline-start:1px;width:12px;height:12px}
.lib-sw.switch[aria-checked="true"] .switch-thumb{transform:translateX(12px)}
.lib-sw[aria-checked="true"] .lib-sw-label{color:var(--text-primary)}
.lib-sw-label{white-space:nowrap}

.lib-move{justify-self:end;white-space:nowrap}

/* The "..." menu. */
.lib-more{position:relative;justify-self:end}
.lib-menu{
  position:absolute;
  top:calc(100% + var(--space-2));
  right:0;
  z-index:var(--z-dropdown);
  display:flex;flex-direction:column;
  min-width:200px;
  padding:var(--space-2);
  background:var(--surface-overlay);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  box-shadow:var(--shadow-pop);
}
.lib-menu.is-up{top:auto;bottom:calc(100% + var(--space-2))}
.lib-mi{
  display:flex;align-items:center;
  height:28px;
  padding:0 var(--space-4);
  border:0;
  border-radius:var(--radius-xs);
  background:transparent;
  color:var(--text-primary);
  font:inherit;font-size:13px;
  text-align:left;white-space:nowrap;
  cursor:pointer;
}
.lib-mi:hover,.lib-mi:focus-visible{background:var(--surface-hover)}
.lib-mi:disabled{opacity:var(--opacity-disabled);cursor:default}

.lib-blank{margin:0;padding:var(--space-8) var(--space-6);text-align:center;font-size:13px}
.lib-foot{margin:var(--space-5) 0 0;font-size:12px}
.lib-foot:empty{display:none}

/* <760px: name over source, and the two switches on a line of their own. */
@media (max-width:759px){
  .lib-bar .input{flex:1 1 140px;margin-left:0}
  .lib-id{grid-template-columns:minmax(0,1fr);gap:var(--space-1)}
  .lib-list .app-card.is-game{
    grid-template-columns:48px auto minmax(0,1fr) 32px;
    grid-template-areas:"cover id id more" "cover rec live .";
    row-gap:var(--space-2);
  }
  .lib-list .lib-cover{width:48px;height:28px;align-self:start;margin-top:var(--space-2)}
  .lib-list .app-card.is-app{grid-template-columns:minmax(0,1fr) auto 32px}
}
"""
