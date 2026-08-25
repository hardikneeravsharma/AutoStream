"""The complete AutoStream stylesheet, emitted as one Python string.

WHY IT IS A STRING AND NOT A .css FILE
    webui.page() serves a single self-contained document -- there is no static asset
    route, and every route is token-gated, so a `<link rel=stylesheet>` would need its
    own authenticated endpoint for no benefit. The server injects this text directly
    after the `:root{}` block that theme.css_vars() produces, which is why nothing here
    may contain the literal `</style>` and why every colour is a var() reference.

THE BUG THIS SHEET IS SHAPED TO PREVENT
    The previous sheet carried a bare `button{padding:14px 18px}` rule. With
    box-sizing:border-box a 38x38 icon button ended up with a 2px content box and the
    glyph inside it was crushed flat. The fix is structural, not a patch:

      1. Bare element selectors set inherited *typography* and reset browser chrome.
         They never set padding, height, width or background on an interactive element.
      2. Every component class states its own box completely -- height, padding,
         background, border, radius -- so it cannot be ambushed by anything above it.
      3. Controls are sized by `height` + `padding-inline` only. There is no vertical
         padding on a button anywhere in this file, so no future padding shorthand can
         reintroduce the crush.
      4. `.btn-icon` restates `padding:0` and a fixed `width` even though `.btn` already
         has no vertical padding, because that is the exact case that broke.

    The one place bare `button`/`input`/`select`/`textarea` selectors do paint a full
    control is inside `#setup-root`, because the first-run wizard's markup predates the
    class vocabulary and uses unclassed elements. That scope is deliberately sealed off
    from the app shell.

ORGANISATION
    tokens -> reset -> shell -> primitives (buttons, forms, surfaces) -> page modules
    (dashboard, library, settings, logs) -> overlays -> setup wizard -> responsive.
    Structural tokens (space, radius, motion, size) live in a second `:root{}` block
    here rather than in theme.py: they do not vary by theme, and a theme file that also
    owned layout constants would have to repeat them five times.

ACCENT BUDGET
    The accent may appear in exactly four places: the focus ring, the active rail /
    settings-nav indicator, the single primary button in a view, and the "on" state of a
    toggle / segmented cell / selected theme swatch. It is never a status colour, never a
    heading colour, never a gradient, and never a stripe on a card. Every accent usage in
    this file is tagged with `ACCENT BUDGET` so an audit is a grep.
"""
from __future__ import annotations

CSS: str = """
/* ==========================================================================
   1. STRUCTURAL TOKENS
   Theme colours arrive from theme.css_vars() in the :root block above this one.
   These are the values that do not change with the theme.
   ========================================================================== */
:root{
  /* space -- 4px grid. 2px and 6px exist only for optical alignment inside controls. */
  --space-1:2px; --space-2:4px; --space-3:6px; --space-4:8px; --space-5:12px;
  --space-6:16px; --space-7:20px; --space-8:24px; --space-9:32px; --space-10:40px;
  --space-11:56px; --space-12:72px;

  --pad-panel:20px 24px;
  --pad-card:20px;
  --pad-card-tight:14px;
  --pad-control-x:12px;
  --gap-control:8px;
  --gap-stack:12px;
  --gap-card:20px;
  --gap-section:32px;
  --gap-grid:20px;

  /* radius -- deliberately NOT uniform. Chassis and data surfaces are square,
     containers are rounded, and exactly two things are pills. */
  --radius-0:0px; --radius-xs:3px; --radius-sm:6px; --radius-md:10px;
  --radius-lg:14px; --radius-pill:999px;

  --border-hair:1px;
  --border-thick:2px;
  --focus-ring-width:2px;
  --focus-ring-offset:2px;

  --shadow-none:none;
  --shadow-rim:inset 0 1px 0 var(--rim);
  --shadow-sm:0 1px 2px var(--shadow-color);
  --shadow-md:0 2px 4px -1px var(--shadow-color), 0 6px 14px -4px var(--shadow-color);
  --shadow-lg:0 4px 8px -2px var(--shadow-color), 0 18px 40px -12px var(--shadow-color);
  --shadow-pop:0 8px 16px -4px var(--shadow-color), 0 28px 60px -16px var(--shadow-color);
  --shadow-inset:inset 0 1px 2px var(--shadow-color);
  --shadow-focus:0 0 0 var(--focus-ring-offset) var(--bg),
                 0 0 0 calc(var(--focus-ring-offset) + var(--focus-ring-width)) var(--border-focus);
  --shadow-live:0 0 0 1px var(--live), 0 0 14px -3px var(--live);

  --dur-instant:90ms; --dur-fast:140ms; --dur-base:200ms; --dur-slow:320ms;
  --dur-pulse:2600ms;
  --ease-standard:cubic-bezier(.32,.72,0,1);
  --ease-out:cubic-bezier(.22,1,.36,1);
  --ease-in:cubic-bezier(.55,0,1,.45);
  --ease-linear:linear;

  --z-base:0; --z-sticky:10; --z-rail:20; --z-topbar:30; --z-dropdown:40;
  --z-scrim:50; --z-modal:60; --z-toast:70;

  --h-control:32px; --h-control-lg:38px; --h-control-sm:28px;
  --h-row-nav:34px; --h-row-list:44px; --h-row-log:22px;
  --h-topbar:56px; --h-rail-brand:56px;
  --size-dot:6px; --size-dot-live:7px;
  --size-icon-sm:14px; --size-icon:16px; --size-icon-lg:20px;
  --icon-stroke:1.5px; --hit-min:32px;
  --meter-height:4px; --rail-indicator-width:2px;

  --opacity-disabled:.45; --opacity-ghost:.62; --opacity-pulse-min:.45;

  /* Every face ships with Windows 11. No @font-face, no network request.
     The 20px split between Display and Text is where WinUI's own ramp switches. */
  --font-display:"Segoe UI Variable Display","Segoe UI",system-ui,-apple-system,sans-serif;
  --font-text:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  --font-micro:"Segoe UI Variable Small","Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  --font-mono:"Cascadia Mono","Cascadia Code",Consolas,ui-monospace,monospace;

  /* layout constants overridden by the responsive block at the bottom */
  --rail-w:216px;
  --gutter:28px;
  --content-max:1280px;
}

/* ==========================================================================
   2. RESET
   Bare element selectors do typography and browser-chrome removal ONLY.
   No element selector in this section sets padding/height/background on a
   control -- see the module docstring.
   ========================================================================== */
*,*::before,*::after{box-sizing:border-box}
*{-webkit-tap-highlight-color:transparent}

html{height:100%;-webkit-text-size-adjust:100%}
body{
  height:100%;
  margin:0;
  background:var(--bg);
  color:var(--text-primary);
  font-family:var(--font-text);
  font-size:14px;
  line-height:1.55;
  font-optical-sizing:auto;
  font-kerning:normal;
  /* No -webkit-font-smoothing: it is a macOS property that thins strokes in
     WebView2 and defeats ClearType. Leave text to DirectWrite. */
  overflow:hidden;
}
::selection{background:var(--selection)}

h1,h2,h3,h4,p,figure,dl,dd,ul,ol{margin:0}
ul,ol{padding:0;list-style:none}
a{color:var(--accent-text);text-decoration:none;text-underline-offset:2px}
a:hover{text-decoration:underline}
b,strong{font-weight:600}
hr{border:0;border-top:var(--border-hair) solid var(--border-subtle);margin:0}
code,kbd,samp,pre{font-family:var(--font-mono);font-size:12.5px}
pre{margin:0}

button,input,select,textarea{
  font:inherit;
  color:inherit;
  letter-spacing:inherit;
  margin:0;
}
button{background:none;border:0;cursor:pointer;text-align:inherit}
button:disabled{cursor:default}
summary{cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}

svg{flex:0 0 auto;display:block}
/* Icons arrive as bare inner markup wrapped by the shell, so they may carry no
   intrinsic size. Give every icon in the app a default box; the logo opts out. */
.app svg,#toasts svg,#setup-root svg,.modal svg{width:var(--size-icon);height:var(--size-icon)}
/* Logo opt-outs. These must match every place a lockup/mark is embedded, or the
   icon default silently squashes it into a 16px smear — width/height attributes
   on the <svg> lose to any CSS declaration. */
.rail-logo svg,#setup-brand svg{width:auto;height:auto}

/* Scrollbars: the only chrome the browser draws for us, so it has to be themed. */
*{scrollbar-color:var(--border-strong) transparent;scrollbar-width:thin}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{
  background:var(--border-strong);
  border-radius:var(--radius-pill);
  border:3px solid transparent;
  background-clip:content-box;
}
::-webkit-scrollbar-thumb:hover{background:var(--text-tertiary);background-clip:content-box}
::-webkit-scrollbar-corner{background:transparent}

/* Focus: :focus-visible ONLY, so mouse users never see a ring. The two-stop ring
   paints a --bg gap then the accent, which keeps it visible on any surface,
   including inside a sunken well and on top of an accent fill.
   ACCENT BUDGET 1/4. */
:focus{outline:none}
:focus-visible{outline:none;box-shadow:var(--shadow-focus)}

.skip-link{
  position:absolute;left:var(--space-4);top:var(--space-4);z-index:var(--z-toast);
  transform:translateY(-200%);
  height:var(--h-control);padding:0 var(--pad-control-x);
  display:inline-flex;align-items:center;
  background:var(--surface-overlay);color:var(--text-primary);
  border:var(--border-hair) solid var(--border-strong);border-radius:var(--radius-sm);
  box-shadow:var(--shadow-rim),var(--shadow-lg);
  font-size:13.5px;font-weight:600;
}
.skip-link:focus-visible{transform:translateY(0)}

/* ==========================================================================
   3. TYPE UTILITIES
   ========================================================================== */
.mono{
  font-family:var(--font-mono);
  font-variant-ligatures:none;
  font-feature-settings:"calt" 0,"tnum" 1,"lnum" 1;
  font-variant-numeric:tabular-nums lining-nums;
}
.num{
  font-weight:500;
  font-variant-numeric:tabular-nums lining-nums;
  font-feature-settings:"tnum" 1,"lnum" 1;
}
.overline{
  font-family:var(--font-micro);
  font-size:10.5px;font-weight:700;line-height:1.2;
  letter-spacing:.09em;text-transform:uppercase;
  color:var(--text-tertiary);
}
.caption{
  font-family:var(--font-micro);
  font-size:12px;font-weight:500;line-height:1.45;
  color:var(--text-tertiary);
}
.muted{color:var(--text-tertiary);font-size:13px;line-height:1.5}
.truncate{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prose{max-width:65ch;color:var(--text-secondary)}
.hide{display:none!important}

.kbd{
  display:inline-flex;align-items:center;justify-content:center;
  min-width:22px;height:22px;padding:0 var(--space-3);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-strong);
  border-bottom-width:2px;
  border-radius:var(--radius-xs);
  font-family:var(--font-mono);font-size:11px;font-weight:600;line-height:1;
  color:var(--text-secondary);
}

/* ==========================================================================
   4. SHELL
   rail (chassis, never scrolls) | [ topbar (chassis) / views (the only scroller) ]
   ========================================================================== */
.app{
  display:grid;
  grid-template-columns:var(--rail-w) minmax(0,1fr);
  height:100vh;
  height:100dvh;
  overflow:hidden;
}

/* ---- rail ---------------------------------------------------------------- */
.rail{
  grid-column:1;
  z-index:var(--z-rail);
  display:flex;
  flex-direction:column;
  gap:var(--space-1);
  min-height:0;
  padding:0 var(--space-4) var(--space-4);
  background:var(--chrome);
  border-inline-end:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-0);   /* chassis is never rounded */
  overflow:hidden;
}
.rail-logo{
  display:flex;
  align-items:center;
  gap:var(--space-4);
  height:var(--h-rail-brand);
  flex:0 0 auto;
  padding-inline:var(--space-2);
  min-width:0;
  color:var(--text-primary);
  font-size:15px;font-weight:600;letter-spacing:-.005em;
  -webkit-app-region:drag;
}
.rail-logo>.pill{margin-inline-start:auto}
.rail-nav{
  display:flex;
  flex-direction:column;
  gap:var(--space-1);
  min-height:0;
  overflow-y:auto;
  overflow-x:hidden;
}
.rail-btn{
  position:relative;
  display:flex;
  align-items:center;
  gap:10px;
  width:100%;
  height:var(--h-row-nav);
  flex:0 0 auto;
  padding:0 10px;            /* inline only -- height owns the vertical box */
  border-radius:var(--radius-sm);
  background:transparent;
  color:var(--text-secondary);
  font-size:14px;font-weight:600;line-height:1;letter-spacing:-.005em;
  transition:background-color var(--dur-instant) var(--ease-standard),
             color var(--dur-instant) var(--ease-standard);
}
.rail-btn>span{
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.rail-btn:hover{background:var(--surface-hover);color:var(--text-primary)}
.rail-btn.is-active{background:var(--accent-muted);color:var(--accent-text)}
/* ACCENT BUDGET 2/4: the 2px marker exists here and in .settings-nav-item, nowhere else. */
.rail-btn.is-active::before{
  content:"";
  position:absolute;
  inset-inline-start:calc(var(--space-4) * -1);
  top:50%;
  transform:translateY(-50%);
  width:var(--rail-indicator-width);
  height:16px;
  border-radius:var(--radius-0);
  background:var(--accent);
}
.rail-btn.is-danger{color:var(--text-secondary)}
.rail-btn.is-danger:hover,
.rail-btn.is-danger:focus-visible{background:var(--danger-muted);color:var(--danger)}
.rail-spacer{
  flex:1 1 auto;
  min-height:var(--space-5);
}
/* The quit control is detached from the four page links by a full-bleed rule so it
   can never be mistaken for a fifth destination. */
.rail-foot{
  flex:0 0 auto;
  display:flex;
  flex-direction:column;
  gap:var(--space-4);
  padding-top:var(--space-5);
  margin-inline:calc(var(--space-4) * -1);
  padding-inline:var(--space-4);
  border-top:var(--border-hair) solid var(--border-subtle);
}
.rail-meta{
  font-family:var(--font-micro);
  font-size:11px;line-height:1.3;
  color:var(--text-tertiary);
  font-variant-numeric:tabular-nums lining-nums;
  padding-inline:10px;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}

/* ---- main + topbar ------------------------------------------------------- */
.main{
  grid-column:2;
  display:flex;
  flex-direction:column;
  min-width:0;
  min-height:0;
  background:var(--bg);
}
.topbar{
  z-index:var(--z-topbar);
  flex:0 0 auto;
  display:flex;
  align-items:center;
  gap:var(--space-5);
  height:var(--h-topbar);
  padding-inline:var(--gutter);
  background:var(--chrome);
  border-bottom:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-0);
  -webkit-app-region:drag;     /* frameless pywebview window drags by its topbar */
  transition:box-shadow var(--dur-base) var(--ease-standard),
             border-color var(--dur-base) var(--ease-standard);
}
.topbar button,.topbar .pill,.topbar .topbar-meta,.topbar input,.topbar select{
  -webkit-app-region:no-drag;
}
.topbar.is-scrolled{border-bottom-color:transparent;box-shadow:var(--shadow-sm)}
.topbar-title{
  font-family:var(--font-display);
  font-size:24px;font-weight:600;line-height:1.18;letter-spacing:-.018em;
  color:var(--text-primary);
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.topbar-meta{
  display:flex;
  align-items:center;
  gap:var(--space-4);
  margin-inline-start:auto;
  min-width:0;
}

/* ---- views --------------------------------------------------------------- */
.views{
  flex:1 1 auto;
  min-height:0;
  overflow-y:auto;
  overflow-x:hidden;
  overscroll-behavior:contain;
  scrollbar-gutter:stable;
}
.view{display:none}
.view.is-active{
  display:block;
  padding:var(--space-8) var(--gutter) var(--space-10);
  max-width:calc(var(--content-max) + var(--gutter) * 2);
  animation:as-view-in var(--dur-base) var(--ease-standard);
}
@keyframes as-view-in{from{opacity:0}to{opacity:1}}

#view-settings.is-active{max-width:calc(880px + var(--gutter) * 2)}
#view-logs.is-active{
  max-width:none;
  height:100%;
  padding-bottom:var(--space-8);
  display:flex;
  flex-direction:column;
  gap:var(--space-5);
  animation:none;             /* the log pane owns its own height; no fade reflow */
}
/* The log page wraps its toolbar and pane in a .card, so the height budget has
   to be handed down through every level. Any link missing min-height:0 makes
   .logview resolve to content height and the pane grows forever instead of
   scrolling inside itself. */
#view-logs.is-active>.card{
  flex:1 1 auto;
  min-height:0;
  display:flex;
  flex-direction:column;
}
#view-logs.is-active>.card>.card-body{
  flex:1 1 auto;
  min-height:0;
  display:flex;
  flex-direction:column;
  gap:var(--space-4);
}

/* ==========================================================================
   5. SURFACES
   .card  = padded elevation-1 container (its children are laid out with gap)
   .panel = UNPADDED elevation-1 container with overflow hidden, for lists,
            scrollers and the metric strip, where children must reach the edge
   ========================================================================== */
.card{
  display:flex;
  flex-direction:column;
  gap:var(--space-6);
  min-width:0;
  padding:var(--pad-card);
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
}
.card-head{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:var(--space-5);
  min-width:0;
}
.card-title{
  font-size:17px;font-weight:600;line-height:1.35;letter-spacing:-.01em;
  color:var(--text-primary);
  min-width:0;
}
.card-sub{
  font-size:13px;font-weight:400;line-height:1.5;
  color:var(--text-secondary);
  max-width:56ch;
}
.card-head>div{display:flex;flex-direction:column;gap:var(--space-2);min-width:0}
.card-body{
  display:flex;
  flex-direction:column;
  gap:var(--space-5);
  min-width:0;
}
.panel{
  min-width:0;
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  overflow:hidden;
}
.divider{
  height:var(--border-hair);
  background:var(--border-subtle);
  border:0;
  flex:0 0 auto;
}

/* ==========================================================================
   6. BUTTONS
   Sized by height + padding-inline. There is NO vertical padding on any button
   in this file; that is what makes the icon-button crush impossible to reintroduce.
   ========================================================================== */
.btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:var(--space-3);
  flex:0 0 auto;
  height:var(--h-control);
  min-width:var(--hit-min);
  padding:0 var(--pad-control-x);
  background:var(--surface);
  color:var(--text-primary);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-sm);
  font-family:var(--font-text);
  font-size:13.5px;font-weight:600;line-height:1;letter-spacing:-.005em;
  white-space:nowrap;
  user-select:none;
  transition:background-color var(--dur-instant) var(--ease-standard),
             border-color var(--dur-instant) var(--ease-standard),
             color var(--dur-instant) var(--ease-standard),
             box-shadow var(--dur-fast) var(--ease-standard);
}
.btn:hover{background:var(--surface-hover)}
.btn:active{background:var(--surface-active)}
.btn:disabled,.btn[aria-disabled="true"]{
  opacity:var(--opacity-disabled);
  border-color:var(--border-subtle);   /* opacity alone reads as a rendering bug */
  background:var(--surface);
}
/* ACCENT BUDGET 3/4: exactly one primary button per view. */
.btn-primary{
  background:var(--accent);
  border-color:var(--accent);
  color:var(--text-on-accent);
}
.btn-primary:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
.btn-primary:active{background:var(--accent-hover);border-color:var(--accent-hover)}
.btn-primary:disabled{background:var(--accent);border-color:var(--accent)}
.btn-danger{
  background:var(--danger);
  border-color:var(--danger);
  color:var(--text-on-danger);
}
.btn-danger:hover,.btn-danger:active{background:var(--danger);border-color:var(--danger);filter:brightness(1.08)}
.btn-warn{
  background:var(--warn);
  border-color:var(--warn);
  color:var(--text-on-warn);
}
.btn-warn:hover,.btn-warn:active{background:var(--warn);border-color:var(--warn);filter:brightness(1.08)}
.btn-ghost{
  background:transparent;
  border-color:transparent;
  color:var(--text-secondary);
}
.btn-ghost:hover{background:var(--surface-hover);color:var(--text-primary)}
.btn-ghost:active{background:var(--surface-active)}
.btn-sm{
  height:var(--h-control-sm);
  padding:0 10px;
  font-size:12.5px;
  gap:var(--space-2);
}
.btn-block{width:100%;flex:1 1 auto}
/* The exact case that broke before: fixed square, zero padding, restated. */
.btn-icon{
  width:var(--h-control);
  height:var(--h-control);
  min-width:0;
  padding:0;
  gap:0;
  flex:0 0 auto;
}
.btn-icon.btn-sm{width:var(--h-control-sm);height:var(--h-control-sm)}
.btn-icon.btn-ghost{color:var(--text-tertiary)}
.btn-icon.btn-ghost:hover{color:var(--text-primary)}
.btn svg{width:var(--size-icon);height:var(--size-icon)}
.btn-sm svg{width:var(--size-icon-sm);height:var(--size-icon-sm)}

/* Segmented control -- the enum control for 2-3 options. */
.seg{
  display:inline-flex;
  align-items:center;
  gap:var(--space-1);
  padding:2px;
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-sm);
}
.seg-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  height:calc(var(--h-control) - 8px);
  padding:0 10px;
  border-radius:var(--radius-xs);
  background:transparent;
  color:var(--text-secondary);
  font-size:13px;font-weight:600;line-height:1;white-space:nowrap;
  transition:background-color var(--dur-instant),color var(--dur-instant);
}
.seg-btn:hover{color:var(--text-primary)}
/* ACCENT BUDGET 4/4 (a): selected segmented cell. */
.seg-btn.is-active{background:var(--accent);color:var(--text-on-accent)}

/* Filter chip -- library "favourites only", log level filters. */
.chip{
  display:inline-flex;
  align-items:center;
  gap:var(--space-3);
  height:var(--h-control-sm);
  padding:0 10px;
  background:var(--surface);
  color:var(--text-secondary);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-sm);
  font-size:12.5px;font-weight:600;line-height:1;white-space:nowrap;
  transition:background-color var(--dur-instant),color var(--dur-instant),
             border-color var(--dur-instant);
}
.chip:hover{background:var(--surface-hover);color:var(--text-primary)}
/* Highlight-type chips on the Clips page. A selected type is filled rather
   than outlined, because the set matters more than any one of them: the user is
   choosing WHICH kinds of round get cut, and needs to see the whole selection
   at a glance. */
.clip-types{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip.is-on{background:var(--accent);border-color:var(--accent);color:#fff}
.chip.is-on:hover{background:var(--accent);color:#fff;filter:brightness(1.08)}
.chip.is-active{background:var(--surface-active);color:var(--text-primary)}
.chip[aria-pressed="false"]{opacity:var(--opacity-ghost)}

/* ==========================================================================
   7. FORMS
   ========================================================================== */
.field{
  display:flex;
  flex-direction:column;
  gap:var(--space-3);
  min-width:0;
}
.field-label{
  font-size:15px;font-weight:600;line-height:1.4;letter-spacing:-.005em;
  color:var(--text-primary);
}
.field-key{
  font-family:var(--font-mono);
  font-size:13px;line-height:1.5;
  color:var(--text-tertiary);
  word-break:break-all;
}
.field-help{
  font-size:13px;font-weight:400;line-height:1.5;
  color:var(--text-secondary);
  max-width:56ch;
}
.field-error{
  display:flex;
  align-items:flex-start;
  gap:var(--space-3);
  font-size:13px;line-height:1.5;
  color:var(--danger);
}
.field-error svg{width:var(--size-icon-sm);height:var(--size-icon-sm);margin-top:2px}
.field-row{
  display:grid;
  grid-template-columns:minmax(0,220px) minmax(0,1fr);
  gap:var(--space-7);
  align-items:start;
  padding-block:var(--pad-card-tight);
  border-top:var(--border-hair) solid var(--border-subtle);
}
.field-row:first-of-type{border-top:0;padding-top:0}
.field-row:last-of-type{padding-bottom:0}
.field-row>*{min-width:0}
.field-inline{
  display:flex;
  align-items:center;
  gap:var(--gap-control);
  flex-wrap:wrap;
  min-width:0;
}
.field-inline>.input,.field-inline>.select{width:auto;flex:1 1 160px;min-width:0}

.input,.select,.textarea{
  display:block;
  width:100%;
  min-width:0;
  height:var(--h-control);
  padding:0 var(--pad-control-x);
  background-color:var(--surface-sunken);
  color:var(--text-primary);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-sm);
  box-shadow:var(--shadow-inset);
  font-family:var(--font-text);
  font-size:14px;
  line-height:normal;
  transition:border-color var(--dur-fast) var(--ease-standard),
             box-shadow var(--dur-fast) var(--ease-standard);
}
.input::placeholder,.textarea::placeholder{color:var(--text-tertiary);opacity:1}
.input:hover,.select:hover,.textarea:hover{border-color:var(--text-tertiary)}
.input:disabled,.select:disabled,.textarea:disabled{
  opacity:var(--opacity-disabled);
  border-color:var(--border-subtle);
}
.input[readonly]{
  color:var(--text-secondary);
  border-color:var(--border-subtle);
  font-family:var(--font-mono);
  font-size:13px;
}
.input.is-mono,.input[type="password"]{
  font-family:var(--font-mono);
  font-size:13px;
  font-variant-ligatures:none;
  font-feature-settings:"calt" 0;
}
.input[type="number"]{font-variant-numeric:tabular-nums lining-nums}
.input.is-invalid,.select.is-invalid,.textarea.is-invalid{border-color:var(--danger)}
.textarea{
  height:auto;
  min-height:112px;
  padding:var(--space-4) var(--pad-control-x);
  font-family:var(--font-mono);
  font-size:12.5px;
  line-height:1.6;
  resize:vertical;
  font-variant-ligatures:none;
  font-feature-settings:"calt" 0;
}
/* The chevron is drawn with two gradients so there is no asset and no data: URI,
   and so it re-colours with the theme. */
.select{
  appearance:none;
  -webkit-appearance:none;
  padding-inline-end:30px;
  background-image:
    linear-gradient(45deg,transparent 50%,var(--text-tertiary) 50%),
    linear-gradient(135deg,var(--text-tertiary) 50%,transparent 50%);
  background-position:calc(100% - 16px) calc(50% + 1px),calc(100% - 11px) calc(50% + 1px);
  background-size:5px 5px,5px 5px;
  background-repeat:no-repeat;
  cursor:pointer;
}
.select option{background:var(--surface);color:var(--text-primary)}

input[type="checkbox"],input[type="radio"]{accent-color:var(--accent);cursor:pointer}
input[type="time"],input[type="number"]{font-variant-numeric:tabular-nums lining-nums}

/* Toggle. Supports both markup shapes: a real checkbox followed by .switch-track,
   and a button[role=switch] carrying .is-on / aria-checked. */
.switch{
  position:relative;
  display:inline-flex;
  align-items:center;
  gap:var(--gap-control);
  min-height:var(--h-control);
  background:none;
  border:0;
  padding:0;
  cursor:pointer;
  color:var(--text-secondary);
  font-size:14px;
  user-select:none;
}
.switch input{
  position:absolute;
  width:1px;height:1px;
  opacity:0;
  margin:0;
  pointer-events:none;
}
.switch-track{
  position:relative;
  flex:0 0 auto;
  width:40px;
  height:22px;
  border-radius:var(--radius-pill);   /* one of only two pills in the app */
  background:var(--track);
  border:var(--border-hair) solid var(--border-strong);
  transition:background-color var(--dur-fast) var(--ease-standard),
             border-color var(--dur-fast) var(--ease-standard),
             box-shadow var(--dur-fast) var(--ease-standard);
}
.switch-thumb{
  position:absolute;
  top:2px;
  inset-inline-start:2px;
  width:16px;
  height:16px;
  border-radius:var(--radius-pill);
  background:var(--text-tertiary);
  transition:transform var(--dur-fast) var(--ease-standard),
             background-color var(--dur-fast) var(--ease-standard);
}
/* ACCENT BUDGET 4/4 (b): the ON state of a toggle. */
.switch input:checked+.switch-track,
.switch.is-on .switch-track,
.switch[aria-checked="true"] .switch-track{background:var(--accent);border-color:var(--accent)}
.switch input:checked+.switch-track .switch-thumb,
.switch.is-on .switch-thumb,
.switch[aria-checked="true"] .switch-thumb{
  transform:translateX(18px);
  background:var(--text-on-accent);
}
.switch input:focus-visible+.switch-track{box-shadow:var(--shadow-focus)}
.switch:focus-visible{box-shadow:none}
.switch:focus-visible .switch-track{box-shadow:var(--shadow-focus)}
.switch:disabled,.switch[aria-disabled="true"]{opacity:var(--opacity-disabled);cursor:default}

/* Editable chip list -- title.hooks, description.tags. */
.taglist{
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:var(--space-3);
  min-width:0;
}
.tag{
  display:inline-flex;
  align-items:center;
  gap:var(--space-2);
  max-width:100%;
  height:var(--h-control-sm);
  padding:0 var(--space-3) 0 var(--space-4);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-xs);
  color:var(--text-secondary);
  font-size:13px;line-height:1;
  min-width:0;
}
.tag>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag-x{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:18px;height:18px;
  padding:0;
  flex:0 0 auto;
  border-radius:var(--radius-xs);
  background:transparent;
  color:var(--text-tertiary);
  transition:background-color var(--dur-instant),color var(--dur-instant);
}
.tag-x svg{width:12px;height:12px}
.tag-x:hover{background:var(--danger-muted);color:var(--danger)}
.tag-add{
  width:auto;
  min-width:140px;
  flex:0 1 200px;
  height:var(--h-control-sm);
  padding:0 var(--space-4);
  background-color:var(--surface-sunken);
  color:var(--text-primary);
  border:var(--border-hair) dashed var(--border-strong);
  border-radius:var(--radius-xs);
  font-family:var(--font-text);
  font-size:13px;
}
.tag-add::placeholder{color:var(--text-tertiary);opacity:1}

/* Theme swatch grid (Settings > Appearance). Paints the theme's own
   bg / surface / accent / live quartet as real stacked plates. */
.swatch-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(112px,1fr));
  gap:var(--space-5);
}
.swatch{
  display:flex;
  flex-direction:column;
  gap:var(--space-3);
  padding:0;
  background:none;
  border:0;
  text-align:start;
}
.swatch-plates{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  height:88px;
  border-radius:var(--radius-xs);
  border:var(--border-thick) solid var(--border-subtle);
  overflow:hidden;
  transition:border-color var(--dur-fast) var(--ease-standard);
}
.swatch-plates i{display:block;height:100%}
.swatch:hover .swatch-plates{border-color:var(--border-strong)}
/* ACCENT BUDGET 4/4 (c): the selected theme swatch. */
.swatch.is-active .swatch-plates{border-color:var(--accent)}
.swatch-label{
  display:flex;
  align-items:center;
  gap:var(--space-3);
  font-size:13px;font-weight:600;
  color:var(--text-secondary);
}
.swatch.is-active .swatch-label{color:var(--text-primary)}
.swatch-label svg{width:var(--size-icon-sm);height:var(--size-icon-sm);color:var(--accent-text)}
.swatch:focus-visible{box-shadow:none}
.swatch:focus-visible .swatch-plates{box-shadow:var(--shadow-focus)}

/* ==========================================================================
   8. DATA DISPLAY
   ========================================================================== */
/* The metric strip: the hairlines ARE the grid gap showing through, so there is
   not one border declaration on a cell, and the cluster reads as one instrument. */
.stat-grid{
  display:grid;
  /* Column count follows the cells the dashboard actually emits (3). A fixed
     repeat(4) left a dead quarter on the strip. */
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:var(--border-hair);
  background:var(--border-subtle);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  overflow:hidden;
}
.stat{
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  gap:var(--space-3);
  min-width:0;
  padding:var(--pad-card-tight) var(--space-4);
  background:var(--surface-raised);
  border-radius:var(--radius-0);
  text-align:center;
}
.stat-value{
  font-family:var(--font-mono);
  font-size:24px;font-weight:500;line-height:1.05;letter-spacing:-.015em;
  color:var(--text-primary);
  font-variant-numeric:tabular-nums lining-nums;
  font-feature-settings:"calt" 0,"tnum" 1,"lnum" 1;
  min-width:0;overflow:hidden;text-overflow:ellipsis;
}
.stat-label{
  font-family:var(--font-micro);
  font-size:10.5px;font-weight:700;line-height:1.2;
  letter-spacing:.09em;text-transform:uppercase;
  color:var(--text-tertiary);
}

/* The status panel: the ONLY in-page element at radius-lg and elevation 2. */
.status-hero{
  display:grid;
  grid-template-columns:auto minmax(0,1fr) auto;
  align-items:center;
  gap:0 var(--space-6);
  padding:var(--pad-panel);
  background:var(--surface-raised);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-lg);
  box-shadow:var(--shadow-rim),var(--shadow-sm);
}
.status-hero>.dot{align-self:center}
.status-phase{
  font-family:var(--font-display);
  font-size:20px;font-weight:600;line-height:1.25;letter-spacing:-.012em;
  color:var(--text-primary);
}
.status-phase.is-live{color:var(--live)}
.status-phase.is-warn{color:var(--warn)}
.status-phase.is-ok{color:var(--ok)}
.status-phase.is-idle{color:var(--idle)}
.status-phase.is-danger{color:var(--danger)}
.status-game{
  font-size:17px;font-weight:600;line-height:1.35;letter-spacing:-.01em;
  color:var(--text-secondary);
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.status-timer{
  grid-column:3;
  justify-self:end;
  font-family:var(--font-mono);
  font-size:34px;font-weight:500;line-height:1;letter-spacing:-.02em;
  color:var(--text-primary);
  font-variant-numeric:tabular-nums lining-nums;
  font-feature-settings:"calt" 0,"tnum" 1,"lnum" 1;
}
.status-meta{
  grid-column:2;
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:var(--space-2) var(--space-5);
  font-size:13px;
  color:var(--text-tertiary);
}
.status-meta.is-blocked{color:var(--danger)}

/* State dot. Colour is never the only channel -- a wordmark always accompanies it. */
.dot{
  width:var(--size-dot);
  height:var(--size-dot);
  flex:0 0 auto;
  border-radius:var(--radius-pill);
  background:var(--idle);
}
.dot.is-live{width:var(--size-dot-live);height:var(--size-dot-live);background:var(--live)}
.dot.is-ok{background:var(--ok)}
.dot.is-warn{background:var(--warn)}
.dot.is-danger{background:var(--danger)}
.dot.is-idle{background:var(--idle)}
.dot.is-debug{background:var(--text-tertiary)}
.dot.is-paused{position:relative;background:var(--idle)}
.dot.is-paused::after{
  content:"";
  position:absolute;
  left:-2px;right:-2px;top:50%;
  height:1px;
  background:var(--bg);
  transform:rotate(-45deg);
}

/* Pills. This and the toggle track are the only pill-shaped things in the app.
   The dot is a ::before so a pill is correct even when written as bare text. */
.pill{
  display:inline-flex;
  align-items:center;
  gap:var(--space-3);
  height:var(--h-control);
  padding:0 var(--pad-control-x);
  border-radius:var(--radius-pill);
  background:var(--idle-muted);
  color:var(--idle);
  font-family:var(--font-mono);
  font-size:10.5px;font-weight:600;line-height:1;letter-spacing:.06em;
  text-transform:uppercase;
  white-space:nowrap;
  max-width:100%;
  min-width:0;
}
.pill::before{
  content:"";
  flex:0 0 auto;
  width:var(--size-dot);
  height:var(--size-dot);
  border-radius:var(--radius-pill);
  background:currentColor;
}
.pill>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pill .mono,.pill .num{font-size:12.5px;letter-spacing:0;text-transform:none;color:var(--text-secondary)}
.pill-idle{background:var(--idle-muted);color:var(--idle)}
.pill-ok{background:var(--ok-muted);color:var(--ok)}
.pill-warn{background:var(--warn-muted);color:var(--warn)}
/* --shadow-live is the tally lamp. It is used here and nowhere else in the product. */
.pill-live{
  background:var(--live-muted);
  color:var(--live);
  box-shadow:var(--shadow-live);
}
.pill-live::before{
  width:var(--size-dot-live);
  height:var(--size-dot-live);
  animation:as-breathe var(--dur-pulse) var(--ease-linear) infinite alternate;
}
@keyframes as-breathe{from{opacity:1}to{opacity:var(--opacity-pulse-min)}}

.meter{
  height:var(--meter-height);
  width:100%;
  background:var(--track);
  border-radius:var(--radius-0);
  overflow:hidden;
}
.meter-fill{
  display:block;
  height:100%;
  width:0;
  background:var(--ok);
  /* Real data must never ease, or the value appears to lag the truth. */
  transition:width var(--dur-slow) var(--ease-linear),
             background-color var(--dur-base) var(--ease-linear);
}
.meter-fill.is-warn{background:var(--warn)}
.meter-fill.is-danger{background:var(--danger)}

/* Definition-list style detail rows (session detail, OBS host:port, ...). */
.deflist{
  display:grid;
  grid-template-columns:auto minmax(0,1fr);
  gap:var(--space-4) var(--space-6);
  align-items:center;
  font-size:14px;
}
.deflist dt{
  font-family:var(--font-micro);
  font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
  color:var(--text-tertiary);
  white-space:nowrap;
}
.deflist dd{
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:var(--text-secondary);
  display:flex;align-items:center;gap:var(--space-4);
}

.empty{
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  gap:var(--space-4);
  padding:var(--space-10) var(--space-6);
  color:var(--text-tertiary);
  font-size:13px;
  text-align:center;
}
.empty svg{width:var(--size-icon-lg);height:var(--size-icon-lg);opacity:var(--opacity-ghost)}

.spin{
  display:inline-block;
  width:15px;height:15px;
  vertical-align:-2px;
  border:2px solid var(--border-subtle);
  border-top-color:var(--accent);
  border-radius:var(--radius-pill);
  animation:as-spin .7s var(--ease-linear) infinite;
}
@keyframes as-spin{to{transform:rotate(360deg)}}

/* ==========================================================================
   9. DASHBOARD LAYOUT
   ========================================================================== */
.dash-grid{
  display:grid;
  grid-template-columns:minmax(0,1fr);
  gap:var(--gap-grid);
  align-items:start;
}
.dash-main{
  display:flex;
  flex-direction:column;
  gap:var(--gap-grid);
  min-width:0;
}
.dash-side{
  display:flex;
  flex-direction:column;
  gap:var(--gap-grid);
  min-width:0;
}
.controls{
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:var(--gap-control);
}

/* ---- countdown ring, sparkline, stat tiles ------------------------------
   Motion policy for this page: every animation below is triggered by a state
   change, not by a clock. The ONE continuous animation is the countdown ring,
   which exists only while a phase is running against a deadline and stops
   itself the moment the window is hidden - this app is open while a game is
   running, and frames spent here are frames the game does not get. */

/* The hero holds text, the ring and the timer. Text takes the slack. */
.status-hero{grid-template-columns:minmax(0,1fr) auto auto}
.hero-text{min-width:0}

.ring{
  position:relative;
  width:96px;height:96px;
  flex:0 0 auto;
  display:grid;
  place-items:center;
}
.ring svg{width:96px;height:96px;transform:rotate(-90deg)}
.ring-track{fill:none;stroke:var(--track);stroke-width:7}
.ring-bar{
  fill:none;
  stroke:var(--accent);
  stroke-width:7;
  stroke-linecap:round;
  transition:stroke .3s ease;
}
.ring-face{position:absolute;display:grid;place-items:center;line-height:1}
.ring-count{
  font-size:26px;font-weight:600;
  color:var(--text-primary);
  font-variant-numeric:tabular-nums;
}
.ring-cap{
  margin-top:3px;
  font-size:9px;font-weight:700;letter-spacing:.1em;
  color:var(--text-tertiary);
}
/* Last five seconds before a broadcast goes public. */
.ring.is-urgent .ring-bar{stroke:var(--danger)}
.ring.is-urgent .ring-count{color:var(--danger)}
.ring.is-urgent{animation:as-breathe-ring 1s ease-in-out infinite}

.abort-bar{
  display:flex;align-items:center;gap:var(--space-5);
  padding:var(--space-4) var(--space-5);
  background:var(--accent-muted);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  animation:as-slide-down .28s ease both;
}
.abort-bar.is-hot{background:var(--danger-muted);border-color:var(--danger)}
.abort-text{flex:1;min-width:0;font-size:13.5px;color:var(--text-secondary)}
.abort-bar.is-hot .abort-text{color:var(--text-primary);font-weight:600}

/* .stat is a <button> now (it picks the graph metric). The base button reset
   strips padding and background, so everything it needs is declared here. */
.stat{
  width:100%;
  position:relative;
  border:var(--border-hair) solid transparent;
  transition:background-color .18s ease,border-color .18s ease,transform .12s ease;
}
.stat:hover{background:var(--surface-hover)}
.stat:active{transform:translateY(1px)}
.stat.is-sel{
  background:var(--surface-active);
  border-color:var(--border-strong);
}
/* Which series the graph is drawing. A 2px underline, not a filled tile. */
.stat.is-sel::after{
  content:"";position:absolute;left:var(--space-5);right:var(--space-5);bottom:0;
  height:2px;background:var(--accent);border-radius:var(--radius-pill);
}
.stat-delta{
  min-height:14px;
  font-size:11px;font-weight:600;
  font-variant-numeric:tabular-nums;
  color:var(--text-tertiary);
}
.stat-delta.is-up{color:var(--ok)}
.stat-delta.is-down{color:var(--text-tertiary)}
.stat-delta.is-in{animation:as-rise .4s ease both}
.stat-value.is-bump{animation:as-bump .42s cubic-bezier(.34,1.56,.64,1) both}

.spark-card .card-body{position:relative}
.spark{width:100%;height:96px;display:block}
.spark-now{
  font-size:15px;font-weight:600;
  font-variant-numeric:tabular-nums;
  color:var(--text-primary);
}
.spark-empty{
  padding:var(--space-7) 0;
  text-align:center;
  font-size:13px;color:var(--text-tertiary);
}

@keyframes as-bump{
  0%{transform:scale(1)}
  40%{transform:scale(1.14)}
  100%{transform:scale(1)}
}
@keyframes as-rise{
  from{opacity:0;transform:translateY(4px)}
  to{opacity:1;transform:none}
}
@keyframes as-slide-down{
  from{opacity:0;transform:translateY(-6px)}
  to{opacity:1;transform:none}
}
/* Distinct name from the pill's as-breathe at the top of this file: a repeated
   @keyframes name is not merged, the later one simply wins for every user of
   it, which silently retimed the live dot. */
@keyframes as-breathe-ring{
  0%,100%{opacity:1}
  50%{opacity:.55}
}
@keyframes as-msg-in{
  from{opacity:0;transform:translateY(6px)}
  to{opacity:1;transform:none}
}
/* New chat lines arrive rather than appear. Capped duration so a burst of ten
   messages does not turn into a wave. */
.chat-msg.is-new{animation:as-msg-in .26s ease both}

/* ---- chat ---------------------------------------------------------------- */
.chat{
  display:grid;
  grid-template-rows:auto minmax(0,1fr) auto;
  min-height:0;
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  overflow:hidden;
}
.chat>.card-head{padding:var(--pad-card-tight) var(--pad-card) var(--space-4)}
.chat-msgs{
  min-height:120px;
  overflow-y:auto;
  overscroll-behavior:contain;
  padding:var(--space-4) var(--pad-card);
  background:var(--surface-sunken);
  box-shadow:var(--shadow-inset);
  border-block:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-0);
  display:flex;
  flex-direction:column;
  gap:var(--space-4);
}
.chat-msg{
  font-size:15px;
  line-height:1.55;
  color:var(--text-secondary);
  word-break:break-word;
  min-width:0;
}
.chat-author{
  font-weight:600;
  color:var(--accent-text);
  margin-inline-end:var(--space-3);
}
.chat-msg.is-owner .chat-author{color:var(--live)}
.chat-msg.is-mod .chat-author{color:var(--ok)}
.chat-row{
  display:flex;
  gap:var(--gap-control);
  align-items:center;
  padding:var(--space-5) var(--pad-card);
  min-width:0;
}
.chat-row .input{flex:1 1 auto;min-width:0}
.chat-empty{
  color:var(--text-tertiary);
  font-size:13px;
  padding:var(--space-6) 0;
  text-align:center;
}

/* ==========================================================================
   10. LIBRARY
   A dense hairline row list, not a tile grid: there is no cover art offline, so a
   tile would be a name and a toggle floating in empty space.
   ========================================================================== */
.searchbar{
  position:sticky;
  top:0;
  z-index:var(--z-sticky);
  display:flex;
  align-items:center;
  gap:var(--gap-control);
  padding:var(--space-5) 0;
  margin-top:calc(var(--space-5) * -1);
  margin-bottom:var(--space-6);
  background:var(--bg);
}
.searchbar .input{flex:1 1 auto;min-width:0}
.applist{
  display:flex;
  flex-direction:column;
  min-width:0;
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  overflow:hidden;
}
.applist-head{
  position:sticky;
  top:0;
  z-index:1;
  display:grid;
  grid-template-columns:minmax(0,1fr) 120px 140px 92px;
  align-items:center;
  gap:var(--space-5);
  height:var(--h-row-nav);
  padding-inline:var(--pad-card-tight);
  background:var(--surface);
  border-bottom:var(--border-hair) solid var(--border-strong);
  font-family:var(--font-micro);
  font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
  color:var(--text-tertiary);
}
.app-card{
  display:grid;
  /* name | source | actions — three tracks for the three cells lib_row emits.
     A fourth track pushed the buttons into a 140px column and left 92px empty. */
  grid-template-columns:minmax(0,1fr) 120px auto;
  align-items:center;
  gap:var(--space-5);
  min-height:var(--h-row-list);
  padding-inline:var(--pad-card-tight);
  border-radius:var(--radius-0);
  border-top:var(--border-hair) solid var(--border-subtle);
  background:transparent;
  transition:background-color var(--dur-instant) var(--ease-standard);
}
.applist>.app-card:first-child{border-top:0}
.applist-head+.app-card{border-top:0}
.app-card:hover{background:var(--surface-hover)}
.app-card>*{min-width:0}
.app-name{
  display:flex;
  align-items:center;
  gap:var(--space-4);
  font-size:15px;font-weight:600;line-height:1.4;letter-spacing:-.005em;
  color:var(--text-primary);
  min-width:0;
}
.app-name>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.app-name svg{width:var(--size-icon-sm);height:var(--size-icon-sm);color:var(--text-tertiary)}
.app-name .is-fav svg,.app-name svg.is-fav{color:var(--warn)}
.app-source{
  font-family:var(--font-micro);
  font-size:12px;font-weight:500;
  color:var(--text-tertiary);
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.app-actions{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  gap:var(--space-3);
  min-width:0;
}

/* ==========================================================================
   11. LOGS
   The pane owns the full height of the content area; the page does not scroll.
   ========================================================================== */
.logbar{
  position:sticky;
  top:0;
  z-index:var(--z-sticky);
  display:flex;
  align-items:center;
  gap:var(--gap-control);
  flex-wrap:wrap;
  flex:0 0 auto;
  min-height:44px;
  padding-block:var(--space-3);
  background:var(--bg);
  border-bottom:var(--border-hair) solid var(--border-subtle);
}
.logbar .input{flex:1 1 180px;min-width:0}
.logview{
  flex:1 1 auto;
  min-height:0;
  overflow:auto;
  overscroll-behavior:contain;
  padding-block:var(--space-4);
  background:var(--surface-sunken);
  box-shadow:var(--shadow-inset);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
}
.log-line{
  display:grid;
  grid-template-columns:88px 64px minmax(0,1fr);
  gap:var(--space-5);
  align-items:baseline;
  min-height:var(--h-row-log);
  padding:2px var(--pad-control-x);
  border-radius:var(--radius-0);
  font-family:var(--font-mono);
  font-size:12.5px;
  line-height:1.6;
  font-variant-ligatures:none;
  font-feature-settings:"calt" 0,"tnum" 1,"lnum" 1;
}
/* A log is a data surface and must not feel clickable: no radius, no lift. */
.log-line:hover{background:var(--surface-hover)}
.log-time{
  color:var(--text-tertiary);
  font-variant-numeric:tabular-nums lining-nums;
  white-space:nowrap;
}
.log-level{
  font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--text-tertiary);
  white-space:nowrap;
}
.log-level.is-info{color:var(--text-tertiary)}
.log-level.is-debug{color:var(--text-tertiary);opacity:var(--opacity-ghost)}
.log-level.is-warn{color:var(--warn)}
.log-level.is-error{color:var(--danger)}
.log-msg{
  min-width:0;
  color:var(--text-secondary);
  white-space:pre-wrap;
  word-break:break-word;
}
.log-line.is-error .log-msg{color:var(--text-primary)}
/* One of only two sanctioned accent plates outside the budget (the other is the
   active nav item), because a search hit must be found, not admired. */
.log-msg mark,.log-hit{
  background:var(--accent-muted);
  color:var(--accent-text);
  border-radius:var(--radius-xs);
  padding:0 2px;
}

/* ==========================================================================
   12. SETTINGS
   ========================================================================== */
.settings-layout{
  display:grid;
  grid-template-columns:minmax(0,1fr);
  gap:var(--gap-section);
  align-items:start;
}
.settings-nav{
  display:flex;
  gap:var(--space-1);
  min-width:0;
  overflow-x:auto;
  overflow-y:hidden;
  position:sticky;
  top:0;
  z-index:var(--z-sticky);
  background:var(--bg);
  padding-block:var(--space-4);
  scrollbar-width:none;
}
.settings-nav::-webkit-scrollbar{display:none}
.settings-nav-item{
  position:relative;
  display:flex;
  align-items:center;
  gap:var(--space-4);
  height:30px;
  flex:0 0 auto;
  padding:0 10px;
  border-radius:var(--radius-sm);
  background:transparent;
  color:var(--text-secondary);
  font-size:14px;font-weight:600;line-height:1;letter-spacing:-.005em;
  white-space:nowrap;
  transition:background-color var(--dur-instant),color var(--dur-instant);
}
.settings-nav-item:hover{background:var(--surface-hover);color:var(--text-primary)}
.settings-nav-item.is-active{color:var(--accent-text)}
.settings-body{
  display:flex;
  flex-direction:column;
  gap:var(--gap-section);
  min-width:0;
  max-width:640px;
}
.settings-section{
  display:flex;
  flex-direction:column;
  gap:var(--space-6);
  min-width:0;
  padding:var(--space-8);
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  scroll-margin-top:var(--space-8);
}
.settings-section-head{
  display:flex;
  flex-direction:column;
  gap:var(--space-2);
  min-width:0;
}
.settings-section-head .card-title{margin:0}
.settings-actions{
  position:sticky;
  bottom:0;
  z-index:var(--z-sticky);
  display:flex;
  align-items:center;
  gap:var(--gap-control);
  height:var(--h-topbar);
  padding-inline:var(--space-6);
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  box-shadow:var(--shadow-md);
}
.settings-actions .grow{margin-inline-start:auto}
.settings-actions>span{
  font-size:13px;
  color:var(--text-secondary);
  font-variant-numeric:tabular-nums lining-nums;
}

/* Advanced disclosure. */
.settings-body details{
  border-top:var(--border-hair) solid var(--border-subtle);
  padding-top:var(--space-6);
}
.settings-body details>summary{
  display:flex;
  align-items:center;
  gap:var(--space-4);
  height:var(--h-row-nav);
  font-size:13px;font-weight:600;
  color:var(--text-secondary);
}
.settings-body details>summary:hover{color:var(--text-primary)}
.settings-body details>summary svg{
  transition:transform var(--dur-fast) var(--ease-standard);
}
.settings-body details[open]>summary svg{transform:rotate(90deg)}
.settings-body details>.settings-body{margin-top:var(--space-6)}

/* The danger zone is OUTLINED, not filled: a permanently red panel stops meaning
   anything by hour two. */
.danger-zone{
  display:flex;
  flex-direction:column;
  gap:var(--space-6);
  padding:var(--space-7);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-md);
}
.danger-zone>.overline{color:var(--danger)}

/* Derived, read-only values live on a sunken plate, not in an input. */
.readonly{
  display:flex;
  align-items:center;
  gap:var(--space-4);
  min-height:var(--h-control);
  padding:var(--space-2) var(--pad-control-x);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-sm);
  box-shadow:var(--shadow-inset);
  font-family:var(--font-mono);
  font-size:13px;
  color:var(--text-secondary);
  word-break:break-all;
  min-width:0;
}
.readonly>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ==========================================================================
   13. OVERLAYS -- toasts and the quit confirmation
   ========================================================================== */
#toasts{
  position:fixed;
  inset-block-end:var(--space-6);
  inset-inline-end:var(--space-6);
  z-index:var(--z-toast);
  display:flex;
  flex-direction:column;
  gap:var(--space-4);
  align-items:flex-end;
  pointer-events:none;
  max-width:min(380px,calc(100vw - var(--space-9)));
}
.toast{
  display:flex;
  align-items:flex-start;
  gap:var(--space-4);
  max-width:100%;
  padding:var(--space-5) var(--space-6);
  background:var(--surface-overlay);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);
  box-shadow:var(--shadow-rim),var(--shadow-lg);
  color:var(--text-primary);
  font-size:13.5px;
  line-height:1.5;
  pointer-events:auto;
  animation:as-toast-in var(--dur-base) var(--ease-out);
}
.toast::before{
  content:"";
  flex:0 0 auto;
  width:var(--size-dot);
  height:var(--size-dot);
  margin-top:6px;
  border-radius:var(--radius-pill);
  background:var(--idle);
}
.toast.is-ok::before{background:var(--ok)}
.toast.is-warn::before{background:var(--warn)}
.toast.is-error::before{background:var(--danger)}
.toast.is-leaving{animation:as-toast-out var(--dur-fast) var(--ease-in) forwards}
@keyframes as-toast-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes as-toast-out{to{opacity:0;transform:translateY(4px)}}

.scrim{
  position:fixed;
  inset:0;
  z-index:var(--z-scrim);
  display:flex;
  align-items:center;
  justify-content:center;
  padding:var(--space-6);
  background:var(--scrim);
  animation:as-fade var(--dur-slow) var(--ease-out);
}
@keyframes as-fade{from{opacity:0}to{opacity:1}}
.modal{
  z-index:var(--z-modal);
  display:flex;
  flex-direction:column;
  gap:var(--space-6);
  width:min(420px,100%);
  padding:var(--space-8);
  background:var(--surface-overlay);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-lg);
  box-shadow:var(--shadow-rim),var(--shadow-pop);
  animation:as-modal-in var(--dur-slow) var(--ease-out);
}
@keyframes as-modal-in{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
.modal-title{
  font-family:var(--font-display);
  font-size:20px;font-weight:600;line-height:1.25;letter-spacing:-.012em;
  color:var(--text-primary);
}
.modal-body{
  font-size:14px;
  line-height:1.55;
  color:var(--text-secondary);
  max-width:56ch;
}
.modal-actions{
  display:flex;
  justify-content:flex-end;
  gap:var(--gap-control);
  flex-wrap:wrap;
}

/* ==========================================================================
   14. SETUP WIZARD (legacy vocabulary)
   The first-run markup predates the class vocabulary and uses unclassed
   <input>/<select>/<button> elements. Those bare selectors are scoped to
   #setup-root so they can never reach the app shell -- see the module docstring.
   ========================================================================== */
#setup-root{
  height:100%;
  overflow-y:auto;
  overscroll-behavior:contain;
  background:var(--bg);
  padding:var(--space-9) var(--space-6) var(--space-11);
}
#setup-root>*{max-width:680px;margin-inline:auto}
#setup-root h1{
  font-family:var(--font-display);
  font-size:24px;font-weight:600;line-height:1.18;letter-spacing:-.018em;
  margin-bottom:var(--space-4);
}
#setup-root h2{
  font-size:17px;font-weight:600;line-height:1.35;letter-spacing:-.01em;
  margin-bottom:var(--space-4);
}
#setup-root p{margin-bottom:var(--space-5);color:var(--text-secondary)}
/* :not(.chk) keeps these element-level defaults from outranking the .chk
   checklist on step 6 — an id selector beats a bare class, so without it the
   app picker collapses into stacked full-width rows. */
#setup-root label:not(.chk){display:block;margin-bottom:var(--space-6)}
#setup-root label:not(.chk)>span{
  display:block;
  margin-bottom:var(--space-3);
  font-size:12.5px;font-weight:600;
  color:var(--text-secondary);
}
#setup-root input:not([type=checkbox]):not([type=radio]),
#setup-root select,#setup-root textarea{
  display:block;
  width:100%;
  height:var(--h-control-lg);
  padding:0 var(--pad-control-x);
  background-color:var(--surface-sunken);
  color:var(--text-primary);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-sm);
  font-family:var(--font-text);
  font-size:14px;
}
#setup-root textarea{
  height:auto;
  min-height:140px;
  padding:var(--space-4) var(--pad-control-x);
  font-family:var(--font-mono);
  font-size:12.5px;
  line-height:1.6;
  resize:vertical;
}
#setup-root select{
  appearance:none;-webkit-appearance:none;
  padding-inline-end:30px;
  background-image:
    linear-gradient(45deg,transparent 50%,var(--text-tertiary) 50%),
    linear-gradient(135deg,var(--text-tertiary) 50%,transparent 50%);
  background-position:calc(100% - 16px) calc(50% + 1px),calc(100% - 11px) calc(50% + 1px);
  background-size:5px 5px,5px 5px;
  background-repeat:no-repeat;
}
#setup-root button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:var(--space-3);
  height:var(--h-control-lg);
  padding:0 var(--space-6);
  background:var(--surface);
  color:var(--text-primary);
  border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-sm);
  font-size:13.5px;font-weight:600;line-height:1;
}
#setup-root button:hover{background:var(--surface-hover)}
#setup-root button:disabled{opacity:var(--opacity-disabled);border-color:var(--border-subtle)}
/* Legacy handler classes emitted by the wizard's nav(): .pri and .gh. */
#setup-root button.pri,#setup-root .btn-primary{
  background:var(--accent);border-color:var(--accent);color:var(--text-on-accent);
}
#setup-root button.pri:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
#setup-root button.gh{background:transparent;border-color:var(--border-subtle);color:var(--text-secondary)}
#setup-root button.gh:hover{background:var(--surface-hover);color:var(--text-primary)}
#setup-root input[type=checkbox]{
  width:auto;height:auto;
  flex:0 0 auto;
  padding:0;
  box-shadow:none;
  border:0;
}

.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 var(--space-5)}
.steps{display:flex;gap:var(--space-3);margin-bottom:var(--space-8);flex-wrap:wrap}
.stp{
  height:4px;flex:1 1 0;min-width:22px;
  border-radius:var(--radius-pill);
  background:var(--border-subtle);
  transition:background-color var(--dur-base) var(--ease-standard);
}
.stp.on{background:var(--accent)}
.stp.done{background:var(--ok)}
.nav{display:flex;gap:var(--space-5);margin-top:var(--space-8)}
.nav button{flex:1 1 0}
.note{
  border-inline-start:var(--border-thick) solid var(--border-strong);
  background:var(--surface);
  border-radius:0 var(--radius-sm) var(--radius-sm) 0;
  padding:var(--space-5) var(--space-6);
  margin-bottom:var(--space-5);
  font-size:14px;
  line-height:1.55;
  color:var(--text-secondary);
}
.note b{color:var(--text-primary)}
.note.warn{border-inline-start-color:var(--warn);background:var(--warn-muted)}
.note.bad{border-inline-start-color:var(--danger);background:var(--danger-muted)}
.note.ok{border-inline-start-color:var(--ok);background:var(--ok-muted)}

/* The first thing a new user is asked: clipper, or streaming as well. Two
   cards rather than a radio group, because the choice decides whether the next
   ten minutes involve a Google Cloud project -- that deserves more than a
   bullet. Stacks on narrow windows; the setup pane is often half a screen. */
.pickrow{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:4px 0 14px}
@media (max-width:720px){.pickrow{grid-template-columns:1fr}}
.pick{
  display:flex;flex-direction:column;gap:6px;text-align:start;cursor:pointer;
  padding:16px;border-radius:var(--radius-lg,12px);
  border:1px solid var(--border-subtle);background:var(--surface-raised);
  color:var(--text-primary);font:inherit;
  transition:border-color .12s ease,background .12s ease,transform .12s ease;
}
.pick:hover{border-color:var(--accent);background:var(--surface-hover)}
.pick:active{transform:translateY(1px)}
.pick:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px}
.pick-title{font-size:1.05rem;font-weight:650}
.pick-sub{color:var(--text-secondary);font-size:.9rem;line-height:1.45}
.pick-meta{margin-top:2px;color:var(--text-tertiary);font-size:.8rem}

/* A results row that can be ticked for upload. The tick sits where the rank
   number was, so the row does not reflow when a run becomes publishable. */
.clip-res-tick{
  width:16px;height:16px;margin:0;accent-color:var(--accent);cursor:pointer;
  justify-self:center;
}
.clip-res.is-up{opacity:.72}
.clip-res.is-up .clip-res-name::after{
  content:"";display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--ok);margin-inline-start:8px;vertical-align:middle;
}

/* Clipping a file the user already has, rather than a recorded session. */
.localclip{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.localclip .field{flex:1 1 220px;min-width:0}
.localclip-path{
  flex:1 1 100%;min-width:0;color:var(--text-secondary);font-size:.85rem;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
ol.steps-list{
  list-style:decimal;
  padding-inline-start:var(--space-7);
  margin-bottom:var(--space-5);
  color:var(--text-secondary);
}
ol.steps-list li{margin-block:var(--space-4)}
.chk{
  display:flex;
  align-items:center;
  gap:var(--space-5);
  padding:var(--space-5);
  margin-bottom:var(--space-3);
  background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-sm);
  cursor:pointer;
}
.chk:hover{background:var(--surface-hover)}
.chk input{width:auto;flex:0 0 auto}
.chk .t{flex:1 1 auto;min-width:0}
.chk .t b{
  display:block;
  font-size:14px;font-weight:600;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.chk .t span{font-family:var(--font-micro);font-size:11px;color:var(--text-tertiary)}
.scroll{max-height:340px;overflow-y:auto;overscroll-behavior:contain;margin-bottom:var(--space-6)}

/* ==========================================================================
   15. RESPONSIVE
   The rail never becomes a bottom tab bar: a resizable desktop window at 420px is
   still driven with a mouse, and a tab strip would exile the quit confirmation
   into an overflow menu.
   ========================================================================== */

/* >=980px: the dashboard becomes two columns and the chat panel sticks. */
@media (min-width:980px){
  .dash-grid{grid-template-columns:minmax(0,1.45fr) minmax(300px,.8fr)}
  .dash-side{
    position:sticky;
    top:var(--space-8);
    max-height:calc(100vh - var(--h-topbar) - var(--space-6) * 4);
  }
  .dash-side>.chat{min-height:0;flex:1 1 auto}
}

/* >=1000px: settings gains its sticky section nav column. */
@media (min-width:1000px){
  .settings-layout{grid-template-columns:minmax(0,196px) minmax(0,1fr)}
  .settings-nav{
    flex-direction:column;
    overflow:visible;
    top:var(--space-8);
    padding-block:0;
    background:transparent;
  }
  /* ACCENT BUDGET 2/4 (b): the same marker as the rail, and nowhere else. */
  .settings-nav-item.is-active::before{
    content:"";
    position:absolute;
    inset-inline-start:calc(var(--space-3) * -1);
    top:50%;
    transform:translateY(-50%);
    width:var(--rail-indicator-width);
    height:16px;
    background:var(--accent);
  }
}

/* >=1560px: a maximised browser on the LAN is the only place content centres. */
@media (min-width:1560px){
  .view.is-active{margin-inline:auto}
}

/* <1120px: tighten the gutters. */
@media (max-width:1119px){
  :root{--gutter:24px}
}

/* <900px: the rail collapses to a 60px icon strip. Labels leave the flow rather
   than merely hiding, so the icons centre honestly. */
@media (max-width:899px){
  :root{--rail-w:60px;--gutter:20px}
  .rail{padding-inline:var(--space-3);align-items:center}
  .rail-logo{justify-content:center;padding-inline:0;gap:0}
  /* Hide the wordmark, never the state dot — it is the whole point of the
     collapsed rail. Scoped to .rail-word so .pill survives. */
  .rail-logo .rail-word{display:none}
  .rail-nav{width:100%}
  .rail-btn{justify-content:center;padding-inline:0;gap:0}
  .rail-btn>span{display:none}
  .rail-btn.is-active::before{inset-inline-start:calc(var(--space-3) * -1)}
  .rail-foot{
    align-items:center;
    margin-inline:calc(var(--space-3) * -1);
    padding-inline:var(--space-3);
  }
  .rail-meta{display:none}
  .settings-nav{margin-inline:0}
}

/* <720px: settings field rows stack; the status capsule sheds its game name. */
@media (max-width:719px){
  .field-row{grid-template-columns:minmax(0,1fr);gap:var(--space-3)}
  .settings-section{padding:var(--space-7)}
  .topbar-meta .capsule-game{display:none}
}

/* <760px: library rows fold their source and scene beneath the name. */
@media (max-width:759px){
  .applist-head{display:none}
  .app-card{
    grid-template-columns:minmax(0,1fr) auto;
    align-items:center;
    row-gap:var(--space-2);
    padding-block:var(--space-4);
    min-height:56px;
  }
  .app-name{grid-column:1;grid-row:1}
  .app-actions{grid-column:2;grid-row:1 / span 2}
  .app-source{grid-column:1;grid-row:2}
  .app-card>.select{grid-column:1;grid-row:3;width:100%}
}

/* <640px: the last gutter step. */
@media (max-width:639px){
  :root{--gutter:16px}
}

/* <560px: metric strip halves, the clock steps down, log rows go single column. */
@media (max-width:559px){
  .stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .status-hero{
    grid-template-columns:auto minmax(0,1fr);
    row-gap:var(--space-4);
  }
  .status-timer{grid-column:1 / -1;justify-self:start;font-size:24px;line-height:1.05}
  .status-meta{grid-column:1 / -1}
  .topbar-title{font-size:20px}
  .topbar-meta .capsule-label{display:none}
  .log-line{grid-template-columns:minmax(0,1fr);gap:0}
  .log-time,.log-level{display:inline;margin-inline-end:var(--space-4)}
  .modal{padding:var(--space-7)}
  #toasts{
    inset-inline:var(--space-5);
    max-width:none;
    align-items:stretch;
  }
}

/* ==========================================================================
   Clips
   Built on .panel / .card / .seg / .meter rather than new primitives. The one
   genuinely new thing is the calibration stage, because dragging a box over a
   video frame has no precedent anywhere else in the app.
   ========================================================================== */

.clip-setup{border-color:var(--warn);gap:var(--space-4)}
.clip-pre{
  margin:0;
  padding:var(--space-5);
  overflow-x:auto;                 /* a winget command line must never widen the page */
  font-size:12px;
  line-height:1.6;
  white-space:pre-wrap;
  color:var(--text-secondary);
  background:var(--surface-sunken);
  border-radius:var(--radius-sm);
}

.clip-list{display:flex;flex-direction:column}
.clip-row{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto auto;
  align-items:center;
  gap:var(--space-5);
  width:100%;
  min-height:var(--h-row-list);
  padding:var(--space-4) var(--pad-card-tight);
  font:inherit;
  color:inherit;
  text-align:start;
  background:none;
  border:0;
  border-top:var(--border-hair) solid var(--border-subtle);
  border-radius:0;
  cursor:pointer;
}
.clip-list>.clip-row:first-child{border-top:0}
.clip-row:hover{background:var(--surface-hover)}
.clip-row.is-active{background:var(--surface-active)}
/* The selected row gets a rail, not an accent fill: the accent budget is spent
   on the primary button, and a filled row would outshout it. */
.clip-row.is-active{box-shadow:inset 3px 0 0 var(--accent)}
.clip-row.is-gone{opacity:var(--opacity-disabled)}
.clip-row>*{min-width:0}
.clip-row-main{display:flex;flex-direction:column;gap:2px;min-width:0}
.clip-row-name{
  overflow:hidden;
  font-weight:550;
  text-overflow:ellipsis;
  white-space:nowrap;
}
.clip-row-sub,.clip-row-when{font-size:12px}
.clip-row-when{white-space:nowrap}

.clip-grid{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:var(--space-7) var(--space-8);
}
.clip-grid .seg{width:100%}
.clip-grid .seg-btn{flex:1 1 0}
/* The style control owns the other three timings, so it reads across the top
   of the grid rather than sitting as a peer of the settings it drives. */
.clip-span2{grid-column:1 / -1}
/* The "this might be the wrong game" notice. Warning-coloured because acting
   on it is optional but ignoring it produces clips of the wrong footage. */
.clip-warn{
  padding:var(--pad-card-tight);
  margin-bottom:var(--space-6);
  border-color:var(--warn);
  display:flex;
  flex-direction:column;
  gap:var(--space-5);
}
.clip-warn .muted{font-size:13px;line-height:1.5}
.clip-actions{
  display:flex;
  flex-wrap:wrap;
  gap:var(--space-5);
  align-items:center;
  justify-content:space-between;
  padding-top:var(--space-6);
  border-top:var(--border-hair) solid var(--border-subtle);
}
.clip-actions .muted{flex:1 1 220px;font-size:12px}

.clip-steps{display:flex;flex-wrap:wrap;gap:var(--space-4);align-items:center}
.clip-step{
  font:600 10.5px/1 var(--font-micro);
  color:var(--text-tertiary);
  text-transform:uppercase;
  letter-spacing:.08em;
}
.clip-step+.clip-step::before{
  margin-inline-end:var(--space-4);
  color:var(--text-tertiary);
  content:"\2192";
}
.clip-step.is-done{color:var(--ok)}
.clip-step.is-now{color:var(--accent)}

.clip-results{display:flex;flex-direction:column}
.clip-res{
  display:grid;
  grid-template-columns:28px minmax(0,1fr) auto auto;
  gap:var(--space-5);
  align-items:center;
  min-height:var(--h-row-nav);
  padding:var(--space-3) 0;
  border-top:var(--border-hair) solid var(--border-subtle);
}
.clip-results>.clip-res:first-child{border-top:0}
.clip-res-rank{font-size:12px;color:var(--text-tertiary);text-align:center}
.clip-res.is-montage .clip-res-rank{color:var(--accent)}
.clip-res-rank svg{width:16px;height:16px}
.clip-res-name{font-weight:550}
.clip-res-meta{font-size:12px}

/* --- calibration ------------------------------------------------------- */

.clip-modal{width:min(760px,calc(100vw - var(--space-8)))}
.clip-cal-stage{
  position:relative;
  display:flex;
  align-items:center;
  justify-content:center;
  aspect-ratio:16/9;
  margin-block:var(--space-5);
  overflow:hidden;
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-sm);
  /* crosshair, because the whole interaction is "draw a box here" */
  cursor:crosshair;
  touch-action:none;
  user-select:none;
}
.clip-cal-stage img{max-width:100%;max-height:100%;pointer-events:none}
.clip-cal-box{
  position:absolute;
  pointer-events:none;
  background:color-mix(in srgb,var(--accent) 18%,transparent);
  border:1px solid var(--accent);
  border-radius:2px;
}
.clip-cal-wait{
  position:absolute;
  inset:0;
  display:flex;
  align-items:center;
  justify-content:center;
  background:var(--scrim);
}
.clip-cal-wait.hide{display:none}
.clip-cal-scrub{flex-wrap:nowrap;margin-bottom:var(--space-6)}
.clip-range{flex:1 1 auto;min-width:0;accent-color:var(--accent)}

.clip-verdict{
  margin-top:var(--space-5);
  padding:var(--space-5);
  font-size:13px;
  line-height:1.5;
  border-left:3px solid var(--border-strong);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
}
.clip-verdict.is-good{border-left-color:var(--ok)}
.clip-verdict.is-weak{border-left-color:var(--warn)}
.clip-verdict.is-bad{border-left-color:var(--danger)}

/* The window is 1120 wide and the rail takes 216, so the options grid has to
   fold well before a phone. */
@media (max-width:880px){
  .clip-grid{grid-template-columns:minmax(0,1fr)}
  .clip-row{grid-template-columns:minmax(0,1fr) auto}
  .clip-row-when{display:none}
}

/* <480px: the library row becomes a single stack. */
@media (max-width:479px){
  .app-card{grid-template-columns:minmax(0,1fr)}
  .app-name,.app-source,.app-card>.select{grid-column:1}
  .app-actions{grid-column:1;grid-row:auto;justify-content:flex-start}
  .grid2{grid-template-columns:1fr}
  .card{padding:var(--pad-card-tight)}
}

/* Reduced motion: durations collapse but the LIVE ring is never removed -- it is
   the only non-motion live cue, and the LIVE wordmark always accompanies it. */
@media (prefers-reduced-motion:reduce){
  :root{
    --dur-instant:1ms;--dur-fast:1ms;--dur-base:1ms;--dur-slow:1ms;
  }
  .view.is-active,.toast,.modal,.scrim{animation:none}
  .pill-live::before{animation:none;opacity:1}
  .switch-thumb,.meter-fill,.btn,.rail-btn,.app-card,.chip,.seg-btn{transition-duration:1ms}
  /* Dashboard motion. The ring keeps its stroke (it is the countdown readout,
     not decoration) but stops breathing; JS separately snaps number rolls and
     drops the per-frame sweep, so the ring steps once per poll instead. */
  .ring.is-urgent,.stat-delta.is-in,.stat-value.is-bump,
  .abort-bar,.chat-msg.is-new{animation:none}
  .ring-bar,.stat{transition-duration:1ms}
  .stat:active{transform:none}
}

/* Forced-colors: hand the whole thing to the OS palette rather than fight it. */
@media (forced-colors:active){
  .btn,.input,.select,.textarea,.card,.panel,.applist,.logview,.settings-section{
    border:1px solid ButtonBorder;
  }
  .rail-btn.is-active::before,.settings-nav-item.is-active::before{background:Highlight}
  :focus-visible{outline:2px solid Highlight;outline-offset:2px;box-shadow:none}
}
"""
