"""The Studio's part of the 2026-10-29 redesign: the clips as a list with the clip in focus beside it,
the reels as a list with a phone-shaped preview, the guided maker's steps across the top with the reel
so far in a bar at the bottom, and the Looks tab without its headline number.

Appended to the end of css.py (see the last lines there), so these rules win over the older Studio
block without that block being rewritten. Tokens only: no colour, radius or shadow is written here
as a number of its own.
"""
from __future__ import annotations

STUDIO_CSS = r"""
/* ==========================================================================
   STUDIO, 2026-10-29: list and inspector, reels and a phone, steps on top
   ========================================================================== */
.studio{gap:var(--space-6)}
.studio-head{align-items:center;gap:var(--space-4)}

/* A key printed on a button whose text the page rewrites (Make a reel, Next): drawn from data-kbd so
   the button's own text stays just its name. */
.studio-kbd[data-kbd]::after{
  content:attr(data-kbd);
  display:inline-flex;align-items:center;justify-content:center;
  min-width:18px;height:18px;padding:0 5px;margin-inline-start:var(--space-4);
  border:var(--border-hair) solid currentColor;border-radius:var(--radius-xs);
  font-size:var(--text-xs);font-weight:600;line-height:1;opacity:.6;
}
.btn .kbd{margin-inline-start:var(--space-4)}
.btn-primary .kbd{color:inherit;border-color:currentColor;opacity:.6}

/* ---- the clips: one quiet line of tools, no hero ------------------------ */
.studio-cliphead{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-4)}
.studio-cliphead .studio-search{flex:0 1 280px;max-width:280px}
.studio-sub{margin:0;color:var(--text-tertiary);font-size:var(--text-xs);
  font-variant-numeric:tabular-nums}
.studio-viewseg .seg-btn{padding:3px 12px}
#studio-tab-reels-n{margin-inline-start:var(--space-2);font-weight:500;color:var(--text-tertiary)}

.studio-browse{display:block;min-width:0}
.studio-browse.has-insp{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:var(--space-6);
  align-items:start}
.studio-lib{min-width:0}

/* the drill-down's way back up: small and grey, the place you are in the primary colour */
.studio-crumbs{margin:0 0 var(--space-3);font-size:var(--text-sm)}

/* folders: calmer cards, no lift on hover */
.studio-folders{grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:var(--space-5);margin-top:0}
.studio-folder-card{border-radius:var(--radius-md)}
.studio-folder-card:hover{box-shadow:none}
.studio-folder-card-name{font-size:var(--text-sm)}
.studio-folder-card-facts{font-size:var(--text-xs);font-variant-numeric:tabular-nums}

/* runs: rows, not cards */
.studio-runs{gap:0;margin-top:0;border-top:var(--border-hair) solid var(--border-subtle)}
.studio-run{padding:var(--space-3) var(--space-2);background:none;border:0;border-radius:0;
  border-bottom:var(--border-hair) solid var(--border-subtle)}
.studio-run:hover{background:var(--surface-hover)}
.studio-run-shot{width:80px;height:45px;border-radius:var(--radius-xs)}
.studio-run-name{font-size:var(--text-sm)}
.studio-run-facts{font-size:var(--text-xs);font-variant-numeric:tabular-nums}
.studio-game-h{font-size:var(--text-md)}

/* a match, a run or a game is a group header over its rows */
.studio-match{gap:0;margin-top:var(--space-6)}
.studio-match:first-child{margin-top:0}
.studio-match-h,.studio-folder-h{padding:var(--space-3) 0;background:none;border:0;border-radius:0;
  font-size:var(--text-xs);color:var(--text-tertiary)}
.studio-match-name,.studio-folder-name{font-size:var(--text-sm);font-weight:600;color:var(--text-primary)}
.studio-match-score{font-size:var(--text-xs);padding:1px 6px}
.studio-folder{margin-top:var(--space-6)}

/* ---- a clip as a row ------------------------------------------------------ */
.studio-rows{display:flex;flex-direction:column;border-top:var(--border-hair) solid var(--border-subtle)}
.studio-clip.studio-crow{display:grid;grid-template-columns:32px minmax(0,1fr);align-items:center;
  flex-direction:row;background:none;border:0;border-bottom:var(--border-hair) solid var(--border-subtle);
  border-radius:0;overflow:visible;box-shadow:none}
.studio-crow:hover{background:var(--surface-hover)}
.studio-crow.is-focus{background:var(--surface-active)}
.studio-crow.is-on{box-shadow:none}
.studio-clip-hit.studio-crow-box{display:grid;place-items:center;width:32px;height:44px;aspect-ratio:auto;
  background:none}
.studio-crow .studio-clip-n{position:static;min-width:16px;width:auto;height:16px;padding:0 3px;
  border-radius:var(--radius-xs);border:var(--border-hair) solid var(--border-strong);background:none;
  color:var(--text-on-accent);font-size:11px}
.studio-crow.is-on .studio-clip-n{background:var(--accent);border-color:var(--accent)}
.studio-crow-box:focus-visible{outline:2px solid var(--border-focus);outline-offset:-2px}
.studio-crow-main{display:grid;grid-template-columns:56px minmax(0,1fr) 84px 64px 52px;align-items:center;
  gap:var(--space-5);min-width:0;height:44px;padding:0 var(--space-4) 0 0;background:none;border:0;
  color:var(--text-secondary);font:inherit;font-size:var(--text-sm);text-align:start;cursor:pointer}
.studio-crow-main:focus-visible{outline:2px solid var(--border-focus);outline-offset:-2px}
.studio-crow-shot{display:block;width:56px;height:32px;object-fit:cover;border-radius:var(--radius-xs);
  background:var(--surface-sunken)}
.studio-crow-name{display:flex;align-items:baseline;gap:var(--space-4);min-width:0;color:var(--text-primary)}
.studio-crow-name .truncate{flex:0 1 auto}
.studio-crow-map{flex:0 0 auto;color:var(--text-tertiary);font-size:var(--text-xs)}
.studio-crow-fav{flex:0 0 auto;color:var(--warn);font-size:var(--text-xs)}
.studio-clip-kills.studio-crow-kills,.studio-clip-dur.studio-crow-dur{position:static;padding:0;
  background:none;border-radius:0;color:var(--text-secondary);font-size:var(--text-xs);font-weight:400}
.studio-crow-dur,.studio-crow-at{text-align:end;font-variant-numeric:tabular-nums}
.studio-crow-at{color:var(--text-tertiary);font-size:var(--text-xs)}
.studio-dots{display:inline-flex;align-items:center;gap:3px}
.studio-dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  border:var(--border-hair) solid var(--text-secondary)}
.studio-dot.is-hs{background:var(--text-secondary)}
.studio-dots b{margin-inline-start:var(--space-2);font-weight:500;color:var(--text-tertiary)}
.studio-crow-none{color:var(--text-tertiary)}
.studio-crow-none.is-warn{color:var(--warn)}

/* ---- the clip in focus ---------------------------------------------------- */
.studio-cinsp,.studio-rinsp{position:sticky;top:var(--space-4);display:flex;flex-direction:column;
  gap:var(--space-5);min-width:0;padding:var(--space-5);background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-lg)}
.studio-cinsp-shot{position:relative;display:block;width:100%;aspect-ratio:16/9;padding:0;border:0;
  border-radius:var(--radius-sm);overflow:hidden;background:var(--surface-sunken);cursor:pointer}
.studio-cinsp-shot img{display:block;width:100%;height:100%;object-fit:cover}
.studio-cinsp-shot:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px}
.studio-cinsp-play{position:absolute;left:var(--space-4);bottom:var(--space-4);display:grid;place-items:center;
  width:32px;height:32px;border-radius:50%;background:var(--on-media-scrim);color:var(--on-media)}
.studio-cinsp-play svg{width:16px;height:16px}
.studio-cinsp-name,.studio-rinsp-name{margin:0;font-size:var(--text-md);font-weight:600;color:var(--text-primary)}
.studio-cinsp-props{display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--space-3) var(--space-5);
  margin:0;font-size:var(--text-sm)}
.studio-cinsp-props dt{color:var(--text-tertiary)}
.studio-cinsp-props dd{margin:0;min-width:0;color:var(--text-primary);overflow-wrap:anywhere;
  font-variant-numeric:tabular-nums}
.studio-cinsp-acts,.studio-rinsp-acts{display:flex;flex-direction:column;gap:var(--space-2);width:100%}
.studio-cinsp-acts .btn,.studio-rinsp-acts .btn{justify-content:space-between;width:100%}

/* ---- the reels: rows and a phone ------------------------------------------ */
.studio-reels{display:flex;flex-direction:column;gap:var(--space-4)}
.studio-reels-head{gap:var(--space-4)}
.studio-rbrowse{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:var(--space-6);align-items:start}
.studio-rlist{display:flex;flex-direction:column;gap:var(--space-4);min-width:0}
.studio-reel-row{display:flex;flex-direction:column;gap:0;border-top:var(--border-hair) solid var(--border-subtle)}
.studio-reel-row .studio-reel{position:relative;display:flex;flex-direction:row;align-items:center;gap:0;
  padding:0;background:none;border:0;border-bottom:var(--border-hair) solid var(--border-subtle);
  border-radius:0;box-shadow:none}
.studio-reel-row .studio-reel:hover{background:var(--surface-hover)}
.studio-reel-row .studio-reel.is-sel{background:var(--surface-active)}
.studio-reel-main{flex:1 1 auto;display:grid;
  grid-template-columns:28px minmax(0,1fr) minmax(0,180px) 56px 64px;align-items:center;
  gap:var(--space-5);min-width:0;height:52px;padding:0 var(--space-4);background:none;border:0;
  color:var(--text-secondary);font:inherit;font-size:var(--text-sm);text-align:start;cursor:pointer}
.studio-reel-main:focus-visible{outline:2px solid var(--border-focus);outline-offset:-2px}
.studio-reel-main .studio-reel-thumb{display:block;width:28px;height:44px;aspect-ratio:auto;
  border-radius:var(--radius-xs);overflow:hidden;background:var(--surface-sunken);cursor:inherit}
.studio-reel-main .studio-reel-thumb img,.studio-reel-main .studio-reel-thumb.is-tall img{
  width:100%;height:100%;object-fit:cover}
.studio-reel-main .studio-reel-name{font-weight:500;color:var(--text-primary)}
.studio-reel-song{color:var(--text-tertiary)}
.studio-reel-main .studio-reel-len{position:static;padding:0;background:none;border-radius:0;
  color:var(--text-secondary);font-size:var(--text-xs);text-align:end;font-variant-numeric:tabular-nums}
.studio-reel-date{color:var(--text-tertiary);font-size:var(--text-xs);text-align:end;
  font-variant-numeric:tabular-nums}
.studio-reel-more{position:relative;flex:0 0 auto;padding-inline-end:var(--space-3)}
.studio-reel-menu{position:absolute;right:var(--space-3);top:calc(100% + var(--space-2));
  z-index:var(--z-dropdown);display:flex;flex-direction:column;min-width:140px;padding:var(--space-2);
  background:var(--surface-overlay);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);box-shadow:var(--shadow-pop)}
.studio-reel-menu button{padding:var(--space-3) var(--space-4);border:0;border-radius:var(--radius-sm);
  background:none;color:var(--danger);font:inherit;font-size:var(--text-sm);text-align:start;cursor:pointer}
.studio-reel-menu button:hover,.studio-reel-menu button:focus-visible{background:var(--danger-muted)}
.studio-rinsp{align-items:center}
.studio-rphone{width:190px;max-width:100%;aspect-ratio:9/16;border-radius:var(--radius-lg);overflow:hidden;
  background:var(--surface-sunken);box-shadow:0 0 0 var(--border-hair) var(--border-subtle)}
.studio-rphone.is-wide{width:100%;aspect-ratio:16/9;border-radius:var(--radius-sm)}
.studio-rphone video{display:block;width:100%;height:100%;object-fit:contain;background:var(--surface-sunken)}
.studio-rinsp-text{display:flex;flex-direction:column;gap:var(--space-1);width:100%;min-width:0}
.studio-rinsp-text p{margin:0;font-size:var(--text-xs)}

/* ---- the guided maker: steps as tabs, the reel so far at the bottom ------- */
.gd-steps{display:flex;flex-wrap:wrap;gap:var(--space-2);padding-bottom:var(--space-4);
  border-bottom:var(--border-hair) solid var(--border-subtle)}
.gd-step{display:flex;align-items:center;gap:var(--space-4);width:auto;
  padding:var(--space-3) var(--space-5) var(--space-3) var(--space-3);background:none;border:0;
  border-radius:var(--radius-sm);color:var(--text-secondary);font-size:var(--text-sm)}
.gd-step:not(:disabled):hover{background:var(--surface-hover);color:var(--text-primary)}
.gd-step.is-on{background:var(--surface-active);color:var(--text-primary)}
.gd-step:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px}
.gd-step .gd-num{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;
  border:var(--border-hair) solid var(--border-strong);font-size:var(--text-xs);font-weight:600;
  color:var(--text-secondary)}
.gd-step.is-on .gd-num{background:var(--accent);border-color:var(--accent);color:var(--text-on-accent)}
.gd-step.is-done .gd-num{border-color:var(--ok);color:var(--ok)}
.gd-step.is-on b{color:var(--text-on-accent)}
.gd-step.is-done span::after{content:none}
.gd-step span{font-weight:500}
.gd-foot{position:sticky;bottom:0;z-index:var(--z-sticky);flex-wrap:nowrap;gap:var(--space-5);
  margin-top:var(--space-4);padding:var(--space-4) var(--space-5);background:var(--surface-raised);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-lg);box-shadow:var(--shadow-md)}
.gd-reelsum{display:flex;flex:1 1 auto;gap:var(--space-7);min-width:0;overflow:hidden}
.gd-reelsum-item{display:flex;flex-direction:column;gap:var(--space-1);min-width:0;max-width:220px}
.gd-reelsum-item b{font-size:var(--text-xs);font-weight:500;color:var(--text-tertiary)}
.gd-reelsum-item span{font-size:var(--text-sm);color:var(--text-primary)}
.gd-reelsum-item.is-empty span{color:var(--text-tertiary)}
.gd-nav{flex:0 0 auto}

/* ---- Looks: the drawers without a headline -------------------------------- */
.bin-calc.studio-looks-head{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-4);padding:0;
  background:none;border:0;border-radius:0;box-shadow:none}
.studio-looks-note{margin:0;font-size:var(--text-xs);font-variant-numeric:tabular-nums}
.studio-looks-intro p{font-size:var(--text-sm)}
.studio-looks-intro .count{margin-inline-start:var(--space-4)}
.bin-sec-head h2{font-family:var(--font-text);font-size:var(--text-md);font-weight:600;letter-spacing:0;
  line-height:1.3}
.bin-sec-head{border-bottom:0;padding-bottom:0}
.bin-sec-head .count{font-size:var(--text-xs);letter-spacing:0}

/* ---- the games in the sidebar -------------------------------------------- */
.studio-railgame{display:flex;align-items:center;gap:var(--space-4);min-width:0}
.studio-railgame .truncate{flex:1 1 auto}
.studio-railn{font-weight:400;font-size:var(--text-xs);color:var(--text-tertiary);
  font-variant-numeric:tabular-nums}
.studio-railgame.is-on{background:var(--surface-active);color:var(--text-primary)}
.studio-railgame:disabled{opacity:.5;cursor:default}

/* ---- narrow windows: the panel goes under the list ------------------------ */
@media (max-width:1119px){
  .studio-browse.has-insp,.studio-rbrowse{grid-template-columns:minmax(0,1fr)}
  .studio-cinsp,.studio-rinsp{position:static}
  .studio-crow-main{grid-template-columns:48px minmax(0,1fr) 64px 44px}
  .studio-crow-at{display:none}
  .studio-reel-main{grid-template-columns:28px minmax(0,1fr) 48px 56px}
  .studio-reel-song{display:none}
  .gd-reelsum{display:none}
}
@media (max-width:639px){
  .studio-crow-main{grid-template-columns:40px minmax(0,1fr) auto 36px;gap:var(--space-4)}
  .studio-crow-shot{width:40px;height:23px}
  .studio-reel-main{grid-template-columns:24px minmax(0,1fr) 40px;gap:var(--space-4)}
  .studio-reel-main .studio-reel-thumb{width:24px;height:40px}
  .studio-reel-date{display:none}
}
"""
