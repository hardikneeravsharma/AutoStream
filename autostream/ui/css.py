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
  /* ---- text drawn ON a video frame -------------------------------------
     NOT A THEME TOKEN, and deliberately not in theme.py: a frame of
     gameplay is not a surface this app controls, and the themes have no say
     over what colour it is. White on a dark scrim is the only pair that
     works over every frame, in every theme.

     THE SCRIM IS THE CONTRAST, and the number is measured rather than
     chosen. Taking the worst case -- a white video frame -- white text on a
     black scrim scores:

         .28 -> 1.98    .35 -> 2.43    .50 -> 3.95
         .55 -> 4.74    .62 -> 6.19    .70 -> 8.45

     so .54 is the floor for normal text at AA and .42 for large. Eight
     different alphas were in use for this one job, and the lightest of them
     was behind 13px white text on the editor's frame handle: 2.43:1, which
     is unreadable over anything bright and was simply never measured. */
  --on-media:#fff;
  --on-media-scrim:rgba(0,0,0,.62);        /* 6.19:1 -- normal text */
  --on-media-scrim-soft:rgba(0,0,0,.55);   /* 4.74:1 -- bold, 14px and up */

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
  /* The parts bin's own voice: condensed caps for its headings, the way an
     edit-house parts list is set. Bahnschrift ships with Windows 11 too. */
  --font-condensed:"Bahnschrift","Segoe UI Variable Display","Arial Narrow",sans-serif;
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
/* WHITE IS NOT A CONTRAST GUARANTEE. Four places filled a shape with
   var(--accent) and then wrote #fff on it, which holds for the dark themes
   that shipped first and fails the moment an accent is light -- and the
   accent is a user setting with a dozen palettes behind it. --text-on-accent
   is the token that already exists for exactly this and is defined per theme;
   the four were simply missed. Measured, not assumed: the same marks are
   already on .btn-primary and .seg-btn.is-active, which is why those were
   never reported. */

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
}

/* NO FADE-IN ON THE VIEW ITSELF, deliberately.
   Reported as the page looking greyed out, and sent as a screen recording.
   Measured off that video by luminance, down the content column:

       y    0-120   bright   the top bar and the sticky streams row
       y  120-440   DARK     p99 4-39 -- a band that was never painted
       y  440-680   bright   p99 133-141

   The rail and the top bar, which are outside this element, were fine
   throughout. So it is a stale composited layer rather than a colour: the
   near-white "be right back" still inside the band measured 42 where the same
   image below the band measured 150.

   Animating opacity here promotes the WHOLE scrolling page into its own
   compositing layer every time a view is shown, and WebView2 under pywebview
   is where that goes wrong -- particularly around hiding the window to the
   tray and showing it again, which this app does on every close. A fade is
   decoration. A page that looks disabled is not a trade worth making. */

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
.seg-btn:disabled{opacity:.55;cursor:default}
.seg-btn:disabled:hover{color:var(--text-secondary)}
/* The dashboard's platform chooser is the width of its card, not of its
   labels: three services of very different name lengths should not give
   YouTube a wider target than Kick. */
#dash-where .seg{display:flex;width:100%}
#dash-where .seg-btn{flex:1 1 0}
#dash-where .field-help{margin-top:var(--space-2)}
/* Instant replay: one button and the line that says whether it will work. */
.replay-row{display:flex;align-items:center;gap:var(--space-5);flex-wrap:wrap}
.replay-row .status-meta{flex:1 1 220px;min-width:0}
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
.chip.is-on{background:var(--accent);border-color:var(--accent);color:var(--text-on-accent)}
.chip.is-on:hover{background:var(--accent);color:var(--text-on-accent);filter:brightness(1.08)}
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
/* Not an error: it works today and may not next week. Same shape as
   .field-error so a line can move between the two without reflowing. */
.field-warn{
  display:flex;
  align-items:flex-start;
  gap:var(--space-3);
  font-size:13px;line-height:1.5;
  color:var(--warn);
}
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
  /* COLUMN COUNT FOLLOWS THE CELLS, and now it really does. This was
     repeat(3) -- written when there were three, with a comment explaining
     that a fixed repeat(4) had left a dead quarter on the strip. Both are
     the same mistake with a different number: the strip gained a fourth cell
     the day instant replay landed, and a hard three dropped it onto a second
     row of its own, full width, under three narrow ones.

     auto-fit with a floor means the strip lays out whatever it is given, and
     wraps instead of crushing when the window is too narrow for them all --
     the numbers are 24px tabular figures and have a width they cannot go
     under. */
  grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
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
/* Mixer faders beside the chat: name, readout and mute on one line, the slider
   the full width of the card under them. On one line the side column left the
   slider about forty pixels -- too short to set anything by. */
.dash-fader{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto auto;
  grid-template-areas:"name db mute" "slider slider slider";
  align-items:center;
  gap:var(--space-3) var(--gap-control);
}
.dash-fader>label{grid-area:name}
.dash-fader>.dash-fader-db{grid-area:db;font-size:12.5px;color:var(--text-secondary)}
.dash-fader>.chip{grid-area:mute}
.dash-fader input[type=range]{grid-area:slider;width:100%;min-width:0;margin:0;
  accent-color:var(--accent)}
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

/* THE NAV SCROLLS AND NOTHING SAID SO. Below 1000px the fifteen sections lie
   in one horizontal strip with the scrollbar hidden, so the last visible one
   was cut mid-word and there was nothing to suggest the rest existed -- the
   page simply looked as though it had eight sections and a rendering fault.

   A fade at whichever edge still has content is the affordance: it reads as
   "this continues", it costs no space, and it cannot be mistaken for a
   control. The classes are set from JS because CSS cannot ask whether a box
   overflows. Neither is set in the >=1000px column layout, where there is no
   overflow to describe. */
.settings-nav.set-more-end{
  -webkit-mask-image:linear-gradient(to right,#000 calc(100% - 40px),transparent);
          mask-image:linear-gradient(to right,#000 calc(100% - 40px),transparent);
}
.settings-nav.set-more-start{
  -webkit-mask-image:linear-gradient(to right,transparent,#000 40px);
          mask-image:linear-gradient(to right,transparent,#000 40px);
}
.settings-nav.set-more-start.set-more-end{
  -webkit-mask-image:linear-gradient(to right,transparent,#000 40px,
                                     #000 calc(100% - 40px),transparent);
          mask-image:linear-gradient(to right,transparent,#000 40px,
                                     #000 calc(100% - 40px),transparent);
}
.settings-nav{scroll-behavior:smooth}

/* ------------------------------------------------------- settings search */
.settings-search{
  position:relative;
  display:flex;
  align-items:center;
  gap:var(--space-3);
  margin-bottom:var(--gap-section);
}
.settings-search .input{flex:1 1 auto;min-width:0}
.settings-search-count{
  flex:0 0 auto;
  color:var(--text-secondary);
  font-size:13px;
  white-space:nowrap;
}
/* A search that matched nothing has to say so. An empty page reads as a
   page that failed to load. */
.settings-noresult{
  padding:var(--space-8);
  color:var(--text-secondary);
  text-align:center;
}
.settings-noresult b{color:var(--text-primary)}
/* While searching, the section headings are what group the results, so they
   carry their own weight rather than reading as one long list. */
.settings-section.is-hit .settings-section-head{
  position:sticky;
  top:0;
  z-index:1;
  background:var(--surface);
}
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

/* The version card. Its own rules are only the few things the shared card
   primitives do not already give it: a warned message, and release notes that
   wrap instead of running off the side. */
#set-ver-msg{margin:0}
#set-ver-msg.is-warn{color:var(--warn)}
#set-ver-body{display:flex;flex-direction:column;gap:var(--space-4)}
#set-ver-meter{width:100%}
.set-ver-notes{
  margin:var(--space-4) 0 0;
  max-height:220px;
  overflow:auto;
  white-space:pre-wrap;
  word-break:break-word;
  font-size:12px;
  line-height:1.6;
  color:var(--text-secondary);
}
#set-ver-noteswrap>summary{
  font-size:13px;font-weight:600;
  color:var(--text-secondary);
  cursor:pointer;
}
#set-ver-noteswrap>summary:hover{color:var(--text-primary)}

.set-diag-text{
  width:100%;
  min-height:220px;
  max-height:420px;
  resize:vertical;
  padding:var(--space-4);
  font-family:var(--font-mono);
  font-size:12px;
  line-height:1.55;
  color:var(--text-secondary);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-sm);
  white-space:pre;
  overflow:auto;
}
#set-diag-msg{margin:0}
#set-diag-msg.is-warn{color:var(--warn)}
#set-diag-body{display:flex;flex-direction:column;gap:var(--space-4)}

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
@media (max-width:719px){.pickrow{grid-template-columns:1fr}}
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
/* The cards are <button>s inside the wizard, and `#setup-root button` outranks
   .pick: it pinned them to one control height and centred them, so three lines
   of text spilled out over the heading on the first screen anyone sees. */
#setup-root button.pick{
  height:auto;display:flex;align-items:stretch;justify-content:flex-start;
  padding:16px;line-height:1.35;font-size:inherit;font-weight:inherit;
  border-radius:var(--radius-lg,12px);border-color:var(--border-subtle);
  background:var(--surface-raised);
}
#setup-root button.pick:hover{border-color:var(--accent);background:var(--surface-hover)}

/* The Google Cloud step: six separate journeys through a console that looks
   nothing like this page, done one at a time with the browser in front of the
   app. Ticks are the reader's own note of where they got to. */
.checklist{display:flex;flex-direction:column;gap:2px;margin:4px 0 10px;padding:0;list-style:none}
.checkitem{margin:0}
.checkitem-box{
  display:flex;align-items:flex-start;gap:10px;cursor:pointer;
  padding:8px 10px;border-radius:var(--radius-sm);
  transition:background-color var(--dur-instant);
}
.checkitem-box:hover{background:var(--surface-hover)}
.checkitem-box input{
  flex:0 0 auto;width:16px;height:16px;margin:2px 0 0;
  accent-color:var(--accent);cursor:pointer;
}
.checkitem-text{flex:1 1 auto;line-height:1.5}
/* Dimmed, never struck through: the text still has to be re-readable when
   somebody comes back to check what they did. */
.checkitem.is-done .checkitem-text{color:var(--text-tertiary)}
.checkitem.is-done .checkitem-text b,
.checkitem.is-done .checkitem-text code{color:inherit}

/* THE ONE TO TAKE. Two choices drawn as equals made the ten-minute path look
   as ordinary as the five-second one. The border carries it rather than a
   fill, so the card still reads as a choice and not as a button that has
   already been pressed -- and so the accent budget is untouched. */
#setup-root button.pick.is-primary,
.pick.is-primary{border-color:var(--accent);background:var(--surface-hover)}
.pick-title{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pick-tag{
  padding:1px 7px;border-radius:999px;
  border:1px solid var(--accent);color:var(--accent-text);
  font-size:.7rem;font-weight:650;letter-spacing:.02em;text-transform:uppercase;
}
/* A chosen platform on the second step. Same vocabulary as the segmented
   control elsewhere, so "this is the one" looks the same everywhere. */
#setup-root button.pick.is-active,
.pick.is-active{border-color:var(--accent);background:var(--surface-hover)}

/* A results row that can be ticked for upload. The tick sits where the rank
   number was, so the row does not reflow when a run becomes publishable. */
/* The handful worth watching first. A border rather than a fill: the row is
   still a row, and the accent budget is spent elsewhere on this page. */
.clip-res.is-best{box-shadow:inset 2px 0 0 var(--accent)}
.clip-res-best{
  margin-inline-start:8px;padding:1px 6px;border-radius:999px;
  border:1px solid var(--accent);color:var(--accent-text);
  font-size:.68rem;font-weight:650;letter-spacing:.02em;text-transform:uppercase;
  vertical-align:middle;white-space:nowrap;
}

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

/* ---------------------------------------------------------- the breakpoints
   ONE SCALE, AND max-width IS ALWAYS ONE LESS THAN min-width.

       480  560  640  720  760  900  980  1000  1120  1560

   A rule that applies below a point uses `max-width: N-1`; a rule that
   applies from it uses `min-width: N`. Written the obvious way instead --
   `max-width: 900px` beside `min-width: 900px` -- BOTH rules apply at
   exactly 900px, and which one wins is then whichever appears later in the
   file. Four pairs were written that way (720, 760, 900 twice, 980) and
   each was a pixel where the page could not say what it meant.

   Three widths are not on the scale yet: 620, 880 and 1100. They are each
   within twenty pixels of a scale point, so snapping them would move real
   layout by a sliver on screens nobody here can look at tonight -- and a
   tidy-up that changes what people see is not a tidy-up. They are listed in
   tests/test_breakpoints.py as debt, which is a different thing from being
   forgotten.

   NOTHING ENFORCES A SCALE EXCEPT A TEST. That one fails on a new
   max-width/min-width pair sharing a pixel, and on a new width that is
   neither on the scale nor in the list of known strays.
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
  .dash-side>#dash-audio{flex:0 0 auto}
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

/* <900px: the gutters tighten. The rail collapses to its icon strip here too, but by the same class every
   other collapse uses (.rail-min, set by shell_rail), not by rules of its own. */
@media (max-width:899px){
  :root{--gutter:20px}
  .settings-nav{margin-inline:0}
}

/* THE RAIL AS AN ICON STRIP (shell_rail): below 900px always, and at any width on every page but the Dashboard
   until the player says otherwise. Labels leave the flow rather than merely hiding, so the icons centre honestly;
   the wordmark goes, never the state dot -- it is the whole point of the collapsed rail. */
.app.rail-min{--rail-w:60px}
/* Hovering the strip opens it, and the page makes room (shell_railPeek). */
.app.rail-min.rail-peek{--rail-w:216px}
.app{transition:grid-template-columns var(--dur-base) var(--ease-standard)}
.app.rail-min:not(.rail-peek) .rail{padding-inline:var(--space-3);align-items:center}
.app.rail-min:not(.rail-peek) .rail-logo{flex-direction:column;justify-content:center;padding-inline:0;gap:var(--space-2)}
.app.rail-min:not(.rail-peek) .rail-logo>.pill{margin:0}
.app.rail-min:not(.rail-peek) .rail-logo .rail-word{display:none}
.app.rail-min:not(.rail-peek) .rail-nav{width:100%}
.app.rail-min:not(.rail-peek) .rail-btn{justify-content:center;padding-inline:0;gap:0}
.app.rail-min:not(.rail-peek) .rail-btn>span{display:none}
.app.rail-min:not(.rail-peek) .rail-btn.is-active::before{inset-inline-start:calc(var(--space-3) * -1)}
.app.rail-min:not(.rail-peek) .rail-foot{align-items:center;margin-inline:calc(var(--space-3) * -1);padding-inline:var(--space-3)}
.app.rail-min:not(.rail-peek) .rail-meta{display:none}
.topbar-rail{flex:none;padding-inline:var(--space-3)}
@media (max-width:899px){.topbar-rail{display:none}}   /* the strip is not a choice there */

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
/* Sits under the list inside the same panel, so it reads as part of the list
   rather than a control floating beneath it. */
.clip-pager{display:flex;align-items:center;justify-content:center;gap:12px;
  padding:10px 12px;border-top:1px solid var(--border-subtle)}
.clip-pager .muted{min-width:9ch;text-align:center;font-variant-numeric:tabular-nums}
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
/* THE PRESET, LIFTED OUT OF THE ROW OF EQUALS. It sets every dial below it,
   so presenting it as one of six identical fields is what made this page read
   as a form to fill in rather than a choice to make. */
.clip-style-field{
  padding:var(--space-5);border-radius:var(--radius-lg);
  background:var(--surface-active);
  border:var(--border-hair) solid var(--border-subtle);
}
.clip-style-field .field-label{font-size:14px;font-weight:600;
  color:var(--text-primary)}
.clip-style-field .seg-btn{padding-block:10px}
.clip-grid-note{
  margin:calc(var(--space-5) * -1) 0 0;font-size:12.5px;
  color:var(--text-tertiary);
}
/* The style control owns the other three timings, so it reads across the top
   of the grid rather than sitting as a peer of the settings it drives. */
.clip-span2{grid-column:1 / -1}
/* The "this might be the wrong game" notice. Warning-coloured because acting
   on it is optional but ignoring it produces clips of the wrong footage. */
/* The trim bar. It shows the scrubbing window: the original clip as a faint
   band behind, what will actually be kept as solid blocks in front, and the
   playhead as a line. Everything is positioned in percentages of the window,
   so the same markup works whether the window is forty seconds or four. */
/* The preview drawn over the player. Positioned in PERCENTAGES of the video
   box so it lands where the burnt-in version will, whatever size the window
   is -- the renderer places captions at fractions of the height too. */
.clip-play-stage{position:relative}
.clip-fx-stage{
  position:absolute;inset:0;
  pointer-events:none;
  display:block;
  overflow:hidden;
}
.clip-fx-cap{
  position:absolute;left:5%;right:5%;
  text-align:center;
  font-family:Impact,"Arial Black","Segoe UI",sans-serif;
  font-weight:900;
  letter-spacing:.01em;
  line-height:1.1;
  /* Over a video frame, with a black outline doing the contrast rather than
     a scrim -- which is what a thumbnail caption has always looked like. */
  color:var(--on-media);
  text-shadow:
    -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000,
    0 3px 6px rgba(0,0,0,.6);
  font-size:clamp(15px, 4.4cqw, 46px);
  opacity:0;
  transition:opacity .12s linear;
}
/* cqw needs a container; without one the clamp falls back to its middle
   value, which is still readable. */
.clip-play-stage{container-type:inline-size}
.clip-fx-cap.is-on{opacity:1}
#clip-fx-cap-top{top:12%}
#clip-fx-cap-middle{top:44%}
#clip-fx-cap-bottom{top:68%}
.clip-fx-held{
  position:absolute;top:var(--space-5);left:50%;transform:translateX(-50%);
  padding:var(--space-3) var(--space-5);
  font-size:11px;font-weight:700;letter-spacing:.12em;
  color:var(--on-media);background:var(--on-media-scrim);
  border-radius:999px;
}
#clip-video{transition:transform .05s linear;transform-origin:center center}

/* The strip under the player: where each effect sits along the clip. */
.clip-fx-timeline{
  position:relative;
  height:34px;
  margin-top:var(--space-3);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  overflow:hidden;
}
.clip-fx-lanes{position:absolute;inset:0}
.clip-fx-bar{
  position:absolute;top:4px;height:26px;
  display:flex;align-items:center;
  padding-inline:6px;
  border-radius:3px;
  font-size:10px;
  color:#fff;
  cursor:pointer;
  overflow:hidden;
  opacity:.9;
}
.clip-fx-bar>i{
  font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.clip-fx-bar:hover{opacity:1;outline:1px solid var(--text-primary)}
/* DRAGGABLE. The body moves the effect and the two edges resize it, which is
   what the timeline is for -- the number boxes underneath stay for the times
   that have to be exact. A freeze and a sound have no end, so they get no
   grips and keep the plain cursor. */
.clip-fx-bar[data-fxdrag]{cursor:grab;touch-action:none}
.clip-fx-bar[data-fxdrag]:active{cursor:grabbing}
.clip-fx-grip{
  position:absolute;top:0;bottom:0;width:7px;
  cursor:ew-resize;
  background:rgba(255,255,255,.55);
  opacity:0;
  transition:opacity .1s ease;
}
.clip-fx-grip.is-a{left:0;border-radius:3px 0 0 3px}
.clip-fx-grip.is-b{right:0;border-radius:0 3px 3px 0}
.clip-fx-bar:hover .clip-fx-grip{opacity:1}
/* The bars are 13px tall, so a 7px grip is most of the width of a short one.
   Below this the whole bar is a move handle and the edges are unreachable --
   which is the right trade: nudging a 0.2s effect by dragging its edge is not
   a gesture anyone can land. */
.clip-fx-bar{min-width:6px}

/* Where a zoom is aimed. On the stage rather than inside the video, so it
   does not scale with the punch-in it describes. */
.clip-fx-aimdot{
  position:absolute;
  width:18px;height:18px;
  margin:-9px 0 0 -9px;
  border-radius:50%;
  border:2px solid #fff;
  box-shadow:0 0 0 2px rgba(0,0,0,.55), 0 0 8px rgba(0,0,0,.5);
  pointer-events:none;
}
.clip-fx-aimdot::after{
  content:"";position:absolute;inset:6px;
  border-radius:50%;background:#fff;
}
.clip-fx-aim.is-on{
  background:var(--accent);
  color:var(--text-on-accent);
}
.clip-fx-bar.is-captions{background:var(--accent);top:2px;height:13px}
.clip-fx-bar.is-zooms{background:var(--ok, #2ea043);top:16px;height:13px}
.clip-fx-bar.is-freezes{background:var(--warn);top:2px;height:13px}
.clip-fx-bar.is-sounds{background:#8957e5;top:16px;height:13px}
.clip-fx-playhead{
  position:absolute;top:0;bottom:0;width:2px;
  background:var(--text-primary);
  pointer-events:none;
}
.clip-fx-grab{
  padding-inline:var(--space-3);
  font-size:13px;line-height:1;
  flex:0 0 auto;
}
.clip-fx-grab:hover{color:var(--accent)}

/* The effects list. One row per effect, each a label, its fields and a way
   to take it off again. Rows wrap rather than scroll sideways: the panel is
   already the narrow column beside the video. */
.clip-fx-list{display:flex;flex-direction:column;gap:var(--space-3);
  margin-top:var(--space-4)}
.clip-fx-row{
  display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;
  padding:var(--space-3) var(--space-4);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-sm);
}
.clip-fx-tag{
  font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--text-secondary);
  min-width:3.6rem;
}
.clip-fx-to{font-size:12px;color:var(--text-secondary)}
.clip-fx-num{width:4.6rem;flex:0 0 auto;font-variant-numeric:tabular-nums}
.clip-fx-text{flex:1 1 7rem;min-width:6rem}
.clip-fx-sel{flex:0 1 auto;min-width:5.5rem}
.clip-fx-sel.grow{flex:1 1 6rem}
.clip-fx-x{margin-inline-start:auto;padding-inline:var(--space-4);
  font-size:16px;line-height:1}
.clip-fx-x:hover{color:var(--danger)}

.clip-gone{
  display:flex;align-items:center;gap:var(--space-4);
  flex-wrap:wrap;
  margin:0 0 var(--space-4);
}

.clip-trim-bar{
  position:relative;
  height:26px;
  margin-top:var(--space-4);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  overflow:hidden;
}
.clip-trim-was{
  position:absolute;top:0;bottom:0;
  background:var(--accent-muted);
}
.clip-trim-keep{position:absolute;inset:0}
.clip-trim-keep>i{
  position:absolute;top:3px;bottom:3px;
  border-radius:2px;
  background:var(--accent);
}
/* Where a removal has been started but not yet ended. */
.clip-trim-keep>b{
  position:absolute;top:0;bottom:0;width:2px;
  background:var(--warn);
}
.clip-trim-head{
  position:absolute;top:0;bottom:0;width:2px;
  background:var(--text-primary);
  opacity:.85;
  pointer-events:none;
}
.clip-trim-chips{
  display:flex;flex-wrap:wrap;gap:var(--space-3);
  margin-top:var(--space-3);
}
.clip-trim-chip{
  display:inline-flex;align-items:center;gap:var(--space-3);
  padding:2px var(--space-4);
  font-size:12px;
  font-variant-numeric:tabular-nums lining-nums;
  color:var(--text-secondary);
  background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:999px;
  cursor:pointer;
}
.clip-trim-chip:hover{color:var(--text-primary);border-color:var(--warn)}
#clip-play-trim.is-warn{color:var(--warn)}

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
  /* The backslash is doubled: this stylesheet is a plain Python string, and
     a single one was read as an octal escape -- the arrow drew as a box
     followed by "92". */
  content:"\\2192";
}
.clip-step.is-done{color:var(--ok)}
.clip-step.is-now{color:var(--accent)}

/* ================================================== while a run is working
   The screen a user looks at longest, and it was the smallest thing on the
   page: a title, four grey words, a hairline bar, and the rest of the window
   empty beneath it. A forty-minute job deserves the room it has.

   The number is sized to be read from across a room, which is where people
   are while this runs. */
.clip-run{padding:var(--space-6)}
.clip-run-head{
  display:flex;justify-content:space-between;align-items:flex-start;
  gap:var(--space-4);margin-bottom:var(--space-6);
}
.clip-run-body{
  display:grid;grid-template-columns:minmax(260px,1fr) minmax(220px,340px);
  gap:var(--space-7);align-items:start;
}
.clip-run-pct{
  font:700 clamp(44px,9vw,92px)/1 inherit;
  color:var(--text-primary);font-variant-numeric:tabular-nums;
  letter-spacing:-.02em;
}
.clip-run-pct span{font-size:.4em;color:var(--text-tertiary);margin-inline-start:.1em}
.clip-run-left{
  margin-top:var(--space-2);font-size:15px;color:var(--accent);font-weight:600;
}
.clip-run-dial .meter{margin-top:var(--space-4)}
.clip-run-elapsed{margin-top:var(--space-2);font-size:12px}

/* A COLUMN. Four stages of very different lengths read better stacked than as
   equal chips in a row, and the current one can then be plainly current. */
.clip-run-steps{list-style:none;margin:0;padding:0;display:flex;
  flex-direction:column;gap:var(--space-2)}
.clip-run-steps .clip-step{
  display:flex;align-items:center;gap:var(--space-3);
  padding:var(--space-3) var(--space-4);border-radius:var(--radius-md);
  font:500 13px/1.2 inherit;letter-spacing:normal;text-transform:none;
  color:var(--text-tertiary);background:transparent;
}
.clip-run-steps .clip-step::before{content:none}
.clip-run-steps .clip-step-dot{
  display:inline-grid;place-items:center;flex:0 0 22px;height:22px;
  border-radius:50%;background:var(--surface-active);
  color:var(--text-tertiary);font-size:11px;font-weight:700;
}
.clip-run-steps .clip-step.is-done{color:var(--text-secondary)}
.clip-run-steps .clip-step.is-done .clip-step-dot{background:var(--ok);color:var(--text-on-ok)}
.clip-run-steps .clip-step.is-now{
  background:var(--surface-active);color:var(--text-primary);font-weight:600;
}
.clip-run-steps .clip-step.is-now .clip-step-dot{background:var(--accent);color:var(--text-on-accent)}
.clip-review-mont{margin-top:var(--space-4)}
@media (max-width:759px){
  .clip-run-body{grid-template-columns:1fr;gap:var(--space-5)}
}

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

/* Stated plainly, with one thing to do about it: fetch the records now, for a
   recording made while AutoStream was not running to fetch them itself. */
.clip-matchline{
  margin:0 0 var(--space-4);
  padding:var(--space-2) var(--space-3);
  border-left:3px solid var(--ok);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
  color:var(--text-muted);
  font-size:var(--font-sm);
}
.clip-matchline.is-warn{border-left-color:var(--warn)}
.clip-matchline.hide{display:none}

/* ------------------------------------------------------------- the player

   Video on the left at whatever aspect the clip is, everything about the clip
   on the right. A vertical clip is tall, so the stage is capped by HEIGHT
   rather than width -- capped by width it would run off the bottom of a
   1120-wide window and the controls would be unreachable. */
.clip-play-body{
  display:grid;
  grid-template-columns:minmax(0,1fr) 20rem;
  gap:var(--space-5);
  align-items:start;
}
.clip-play-left{display:flex;flex-direction:column;gap:var(--space-3);min-width:0}
.clip-play-stage{
  display:flex;
  align-items:center;
  justify-content:center;
  background:#000;
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  overflow:hidden;
  max-height:62vh;
}
#clip-video{max-width:100%;max-height:62vh;display:block}
/* Fullscreen is the player column: the picture takes what is left over after
   the effects lane and the play bar, so the controls stay on screen. */
.clip-play-left:fullscreen{background:#000;padding:var(--space-3);gap:var(--space-2)}
.clip-play-left:fullscreen > :not(.clip-play-stage):not(.clip-fx-timeline):not(.clip-play-bar){display:none}
.clip-play-left:fullscreen .clip-play-stage{flex:1 1 auto;min-height:0;max-height:none;border:0;border-radius:0}
.clip-play-left:fullscreen #clip-video{max-height:100%;max-width:100%;width:auto;height:100%}

.clip-play-bar{
  display:flex;
  align-items:center;
  gap:var(--space-2);
  flex-wrap:wrap;
  padding:var(--space-2) var(--space-3);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
}
.btn-icon{
  min-width:2.2rem;
  padding:.3rem .5rem;
  font-size:1rem;
  line-height:1;
}
.clip-play-time{flex:0 0 auto;font-size:var(--font-sm);color:var(--text-muted)}
.clip-play-seek{flex:1 1 8rem;min-width:6rem;accent-color:var(--accent)}
.clip-play-vol{flex:0 0 4.5rem;accent-color:var(--accent)}
.clip-play-speed{flex:0 0 5.5rem;max-width:5.5rem}

/* Volume and speed, beside every player in the app (shell.js mediaKnobs). */
.media-knobs{display:inline-flex}
.knobs{display:inline-flex;align-items:center;gap:var(--space-2);flex:0 0 auto}
.knob-vol{display:inline-flex;align-items:center;gap:.3rem;color:var(--text-muted);font-size:var(--font-sm)}
.knob-vol input{width:5rem;accent-color:var(--accent)}
.knob-rate{width:auto;min-width:4.6rem;padding-top:.2rem;padding-bottom:.2rem;font-size:var(--font-sm)}

.clip-play-right{display:flex;flex-direction:column;gap:var(--space-3)}
.clip-play-h{
  margin:0 0 var(--space-2);
  font-size:var(--font-sm);
  font-weight:600;
  color:var(--text-muted);
  text-transform:uppercase;
  letter-spacing:.04em;
}
/* Two columns so the values line up; the labels are short by design. */
.clip-play-info{
  display:grid;
  grid-template-columns:5.5rem minmax(0,1fr);
  gap:.2rem var(--space-2);
  margin:0;
  font-size:var(--font-sm);
}
.clip-play-info dt{color:var(--text-muted)}
.clip-play-info dd{margin:0;overflow-wrap:anywhere}
.clip-play-apply{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:var(--space-2);
  flex-wrap:wrap;
}

/* ------------------------------------------- clips a run already produced */
.clip-made-list{display:flex;flex-direction:column}
.clip-made-row{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto auto;
  gap:var(--space-3);
  align-items:center;
  padding:var(--space-2) 0;
  border-top:1px solid var(--border);
}
.clip-made-row:first-child{border-top:0}
.clip-made-name{font-weight:600;overflow-wrap:anywhere}

/* ---------------------------------------- reviewing a plan before cutting

   A still from the recording is the only thing that says WHICH moment a row
   is, so it leads the row and everything else sits beside it. 16:9 at a fixed
   width, because the frames arrive at whatever the source was. */
.clip-review-list{display:flex;flex-direction:column;gap:var(--space-3)}
.clip-review-row{
  display:grid;
  grid-template-columns:170px minmax(0,1fr);
  gap:var(--space-4);
  padding:var(--space-3);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
}
.clip-review-thumb{
  width:170px;
  aspect-ratio:16/9;
  object-fit:cover;
  border-radius:var(--radius-sm);
  background:var(--surface-raised);
  display:block;
}
.clip-review-body{display:flex;flex-direction:column;gap:var(--space-2);min-width:0}
.clip-review-head{
  display:flex;
  align-items:baseline;
  gap:var(--space-3);
  flex-wrap:wrap;
}
.clip-review-field{
  display:flex;
  align-items:center;
  gap:var(--space-2);
  flex-wrap:wrap;
}
/* The label is fixed-width so the two rows' inputs line up under each other. */
.clip-review-field>.field-label{flex:0 0 4.5rem;margin:0}
.clip-review-field>.input{flex:1 1 12rem;min-width:0}
.clip-review-voice{flex:0 0 11rem;max-width:11rem}
.clip-review-field>.input:disabled,
.clip-review-voice:disabled{opacity:.5}

/* ------------------------------------------ the tools that are not Python

   One row per tool, and the state leads it. Whether ffmpeg is there is the
   whole question the card answers, so it is read first and the explanation
   second. */
.clip-tools-list{display:flex;flex-direction:column;gap:var(--space-3)}
.clip-tool{
  display:grid;
  grid-template-columns:6.5rem minmax(0,1fr);
  gap:var(--space-3);
  align-items:start;
  padding:var(--space-3);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
}
.clip-tool p{margin:.25rem 0 0}
.clip-tool-tag{
  justify-self:start;
  padding:.1rem .5rem;
  border-radius:999px;
  font-size:.75rem;
  font-weight:600;
  text-transform:uppercase;
  letter-spacing:.03em;
  background:var(--warn-bg,rgba(210,153,34,.16));
  color:var(--warn,#d29922);
}
.clip-tool.is-ok .clip-tool-tag{
  background:var(--ok-bg,rgba(63,185,80,.16));
  color:var(--ok,#3fb950);
}

/* -------------------------------------------- choosing the part to clip

   A strip of stills across the whole file, with the part that will NOT be
   read dimmed rather than hidden -- the frames on either side are how you
   know the selection is in the right place. */
.clip-strip{
  display:grid;
  grid-auto-flow:column;
  grid-auto-columns:1fr;
  gap:2px;
  border-radius:var(--radius-sm);
  overflow:hidden;
  background:var(--surface-sunken);
}
.clip-frame{
  position:relative;
  display:block;
  padding:0;
  border:0;
  background:none;
  cursor:pointer;
  line-height:0;
  transition:opacity .12s ease;
}
.clip-frame img{
  width:100%;
  aspect-ratio:16/9;
  object-fit:cover;
  display:block;
  background:var(--surface-raised);
}
.clip-frame-t{
  position:absolute;
  left:0;
  bottom:0;
  padding:.05rem .3rem;
  font-size:.7rem;
  line-height:1.4;
  font-variant-numeric:tabular-nums;
  color:var(--on-media);
  background:var(--on-media-scrim);
}
.clip-frame.is-out{opacity:.28}
.clip-frame.is-out .clip-frame-t{opacity:.7}
.clip-frame:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}

/* The two handles sit in the same track, so the span between them reads as
   one selection rather than as two unrelated sliders. Stacking them means
   only the top one can be grabbed, so pointer events are turned off on the
   track and back on for the thumbs alone. */
.clip-range{position:relative;height:2rem;margin-top:var(--space-2)}
.clip-range-in{
  position:absolute;
  left:0;
  right:0;
  top:.5rem;
  width:100%;
  margin:0;
  background:none;
  pointer-events:none;
  -webkit-appearance:none;
  appearance:none;
}
.clip-range-in::-webkit-slider-runnable-track{
  height:4px;border-radius:2px;background:var(--border);
}
.clip-range-in::-moz-range-track{
  height:4px;border-radius:2px;background:var(--border);
}
.clip-range-in::-webkit-slider-thumb{
  -webkit-appearance:none;
  pointer-events:auto;
  width:16px;height:16px;margin-top:-6px;
  border-radius:50%;
  border:2px solid var(--surface);
  background:var(--accent);
  cursor:ew-resize;
}
.clip-range-in::-moz-range-thumb{
  pointer-events:auto;
  width:16px;height:16px;
  border-radius:50%;
  border:2px solid var(--surface);
  background:var(--accent);
  cursor:ew-resize;
}

/* The window is 1120 wide and the rail takes 216, so the options grid has to
   fold well before a phone. */
@media (max-width:880px){
  .clip-grid{grid-template-columns:minmax(0,1fr)}
  .clip-row{grid-template-columns:minmax(0,1fr) auto}
  .clip-row-when{display:none}
  .clip-review-row{grid-template-columns:minmax(0,1fr)}
  .clip-review-thumb{width:100%}
  .clip-tool{grid-template-columns:minmax(0,1fr)}
  /* Twelve stills across a narrow window are twelve smears. Half of them at
     twice the width still says where each part of the file is. */
  .clip-strip>.clip-frame:nth-child(even){display:none}
  .clip-play-body{grid-template-columns:minmax(0,1fr)}
  .clip-made-row{grid-template-columns:minmax(0,1fr) auto}
}

/* <480px: the library row becomes a single stack. */
@media (max-width:479px){
  .app-card{grid-template-columns:minmax(0,1fr)}
  .app-name,.app-source,.app-card>.select{grid-column:1}
  .app-actions{grid-column:1;grid-row:auto;justify-content:flex-start}
  .grid2{grid-template-columns:1fr}
  .card{padding:var(--pad-card-tight)}
  /* A title beside its action button ran the button off the card's edge on a
     phone ("Build a report"); below 480px the button drops under the title. */
  .card-head{flex-wrap:wrap}
  /* The log's full path is one unbroken word, wider than a phone. */
  #log-path{overflow-wrap:anywhere}
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

CLIPS_FLOW_CSS = """
/* ---------------------------------------------------------------- clips rail
   NAVIGATION, and it did not start that way. The page was one column with
   every stage's cards on it, and the rail only scrolled you around that
   column -- which meant a first-time user met a part picker, three ways to
   read a match, a sheet of style options and a review table all at once.

   Now the rail opens a stage and the others go away. Nothing is gated: a
   stage you have not reached, and one you finished ten minutes ago, are both
   one click from here. */
.clip-rail{
  display:flex;flex-wrap:wrap;gap:var(--space-2);
  list-style:none;margin:0 0 var(--space-6);padding:0;
}
.clip-rail-step button{
  display:inline-flex;align-items:center;gap:var(--space-2);
  padding:6px 12px 6px 6px;border:var(--border-hair) solid var(--border-subtle);
  border-radius:999px;background:var(--surface);color:var(--text-secondary);
  font-size:12px;cursor:pointer;
}
.clip-rail-step button:hover{background:var(--surface-hover)}
.clip-rail-dot{
  display:inline-grid;place-items:center;width:20px;height:20px;
  border-radius:50%;background:var(--surface-active);
  color:var(--text-secondary);font-size:11px;font-weight:600;
}
.clip-rail-step.is-done button{color:var(--text-primary)}
.clip-rail-step.is-done .clip-rail-dot{background:var(--accent);color:var(--text-on-accent)}
.clip-rail-step.is-now button{
  border-color:var(--accent);color:var(--text-primary);
}
/* WHERE YOU ARE, now that the rail moves you rather than scrolling you. A tick
   means finished and the filled pill means open, so a step can be both -- you
   came back to it -- and the two have to be told apart at a glance. */
.clip-rail-step.is-here button{
  border-color:var(--accent);background:var(--surface-active);
  color:var(--text-primary);font-weight:600;
  box-shadow:0 0 0 1px var(--accent) inset;
}
/* A stage with nothing in it yet. Shown rather than removed, so the number of
   stages does not change under the user as a run progresses -- but plainly
   not somewhere to go. */
.clip-rail-step.is-locked button{
  opacity:.45;cursor:not-allowed;
}
.clip-rail-step.is-locked button:hover{background:var(--surface)}
.clip-rail{position:sticky;top:0;z-index:5;background:var(--bg);
  padding-top:var(--space-2)}

/* One stage at a time. `.hide` is each card's own reason to be out of sight;
   this is the stage gate, and either one wins. */
.clip-offstep{display:none !important}

/* Always in the same place, whatever the stage is made of. */
.clip-stepnav{
  display:flex;justify-content:space-between;gap:var(--space-3);
  margin-top:var(--space-6);padding-top:var(--space-4);
  border-top:var(--border-hair) solid var(--border-subtle);
}
.clip-stepnav button:disabled{opacity:.4;cursor:default}
@media (max-width:620px){
  .clip-rail{gap:4px}
  .clip-rail-step button{font-size:11px;padding:5px 9px 5px 5px}
}

/* ------------------------------------------------------- how to read a match
   Three ways that differ by an order of magnitude in both time and quality,
   so each one carries its real cost against the stretch actually selected.
   "Fast" and "slow" is not a choice anybody can make; "about 40 minutes" is. */
.clip-ways{display:grid;gap:var(--space-3)}
@media (min-width:900px){.clip-ways{grid-template-columns:repeat(3,1fr)}}
.clip-way{
  display:flex;flex-direction:column;gap:var(--space-2);text-align:left;
  padding:var(--space-4);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);background:var(--surface);cursor:pointer;
  color:var(--text-secondary);font:inherit;
}
.clip-way:hover{background:var(--surface-hover)}
.clip-way.is-on{border-color:var(--accent);background:var(--surface-active)}
.clip-way-top{display:flex;flex-direction:column;gap:2px}
.clip-way-top b{color:var(--text-primary);font-size:14px}
.clip-way-cost{color:var(--accent);font-size:12px;font-variant-numeric:tabular-nums}
.clip-way-why{font-size:12px;line-height:1.45}

/* ------------------------------------------------------- card calibration
   The frames are the user's own, chosen because a tally is probably in them.
   Calibrating against a picture of somebody else's HUD is how the shipped
   region came to be wrong for anyone not on 16:9 at this HUD scale. */
.clip-cal-shots{display:grid;gap:var(--space-3)}
@media (min-width:760px){.clip-cal-shots{grid-template-columns:repeat(3,1fr)}}
.clip-cal-shot{position:relative;margin:0}

/* WAITING, SHOWN AS WAITING.
   Sampling this panel's frames reads about a minute of the recording --
   measured at 57.7s on a 1h51m file -- and while it ran the card showed its
   title, a subtitle telling you to drag a box, and one line of grey prose.
   Nothing moved and nothing was reserved, so it read as broken rather than
   busy, and the instruction was for frames that were not there yet.
   Six placeholders in the same grid the frames land in: the space is held,
   the shimmer says work is happening without anyone reading a word, and
   nothing jumps when the real frames arrive. */
.clip-cal-skel{
  aspect-ratio:16/9;
  border-radius:var(--radius-sm);
  border:var(--border-hair) solid var(--border-subtle);
  background:linear-gradient(100deg,
    var(--surface-sunken) 30%, var(--surface-raised) 50%,
    var(--surface-sunken) 70%);
  background-size:220% 100%;
  animation:as-shimmer 1.4s var(--ease-linear) infinite;
}
@keyframes as-shimmer{to{background-position:-120% 0}}

/* The status line while it works. NOT .muted: this is the one thing on the
   card that is true at that moment, and it was the same grey as the prose
   around it. */
.clip-cal-busy{
  display:flex;
  align-items:center;
  gap:var(--space-3);
  margin:0 0 var(--space-4);
  padding:var(--space-3) var(--space-4);
  border-left:3px solid var(--accent);
  border-radius:var(--radius-sm);
  background:var(--surface-sunken);
  color:var(--text-primary);
  font-size:13px;
}
.clip-cal-busy .spin{flex:0 0 auto}

@media (prefers-reduced-motion:reduce){
  .clip-cal-skel{animation:none}
}
.clip-cal-shot img{
  display:block;width:100%;border-radius:var(--radius-sm);
  border:var(--border-hair) solid var(--border-subtle);
  /* THE SAME SHAPE AS THE PLACEHOLDER IT REPLACES. Six stills of a 1080p
     recording arrive one at a time over a slow connection to a local server,
     and with no reserved height each arrival re-laid out everything below it
     -- six reflows of a scrolling page, which is the other half of what
     leaves a band of it unpainted. Reserved, the grid never moves, and the
     frames simply appear where the placeholders were. */
  aspect-ratio:16/9;
  object-fit:cover;
  background:var(--surface-sunken);
}
.clip-cal-shot figcaption{
  margin-top:4px;font-size:11px;color:var(--text-secondary);
  font-variant-numeric:tabular-nums;
}
.clip-cal-frame{position:relative;display:block;overflow:hidden;border-radius:var(--radius-sm)}
.clip-cal-frame .clip-cal-box{
  position:absolute;border:2px solid var(--accent);border-radius:2px;
  background:none;
  box-shadow:0 0 0 9999px rgba(0,0,0,.35);pointer-events:none;
}
.clip-cal-verdict{
  padding:var(--space-4);border-radius:var(--radius-sm);
  border:var(--border-hair) solid var(--border-subtle);font-size:13px;
}
.clip-cal-verdict.is-good{border-color:var(--ok,#3fb950)}
.clip-cal-verdict.is-bad{border-color:var(--warn)}
.clip-cal-nums{
  display:block;margin-top:6px;font-size:11px;color:var(--text-secondary);
  font-variant-numeric:tabular-nums;
}

/* ------------------------------------------------------------ match videos
   Marvel Rivals: what to make, the outro, the matches found earlier, and the
   videos a run made, grouped by match. */
.clip-mv{display:flex;flex-direction:column;gap:var(--space-5);margin-top:var(--space-4)}
@media (min-width:900px){.clip-mv-make{grid-template-columns:repeat(2,1fr)}}
.clip-mv-tile .clip-way-top b{display:flex;align-items:center;gap:var(--space-3)}
.clip-mv-box{
  display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;
  width:18px;height:18px;border-radius:var(--radius-xs);font-size:12px;
  border:var(--border-hair) solid var(--border-strong);color:var(--text-on-accent);
}
.clip-mv-tile.is-on .clip-mv-box{background:var(--accent);border-color:var(--accent)}
.clip-mv-tile .clip-way-cost{padding-left:26px}
.clip-mv-tile .clip-way-why{padding-left:26px}
.clip-mv-outro{
  display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-4);
  padding:var(--space-3);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);background:var(--surface-sunken);
}
.clip-mv-outro-thumb{
  position:relative;flex:0 0 auto;width:160px;aspect-ratio:16/9;padding:0;
  border:0;border-radius:var(--radius-sm);overflow:hidden;cursor:pointer;
  background:var(--surface);max-width:100%;
}
.clip-mv-outro-thumb img{display:block;width:100%;height:100%;object-fit:cover}
.clip-mv-outro-play{
  position:absolute;inset:auto auto 6px 6px;width:26px;height:26px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:11px;
  background:var(--on-media-scrim);color:var(--on-media);
}
.clip-mv-outro-thumb:hover .clip-mv-outro-play{background:var(--accent)}
.clip-mv-outro-text{display:flex;flex-direction:column;gap:2px;flex:1 1 180px;min-width:0}
.clip-mv-outro-text b{color:var(--text-primary);overflow-wrap:anywhere}
.clip-mv-outro-video{display:block;width:100%;max-width:480px;margin-top:var(--space-3);
  border-radius:var(--radius-sm);background:#000}
.clip-mv-warn{color:var(--warn)}
.clip-known{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3);
  margin-top:var(--space-3)}
.clip-known-lead{font:600 10.5px/1 var(--font-micro);text-transform:uppercase;
  letter-spacing:.08em;color:var(--text-tertiary);margin-right:var(--space-2)}
.clip-known-chip{
  display:inline-flex;align-items:center;gap:var(--space-2);height:var(--h-control-sm);
  padding:0 var(--space-4);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-pill);background:var(--surface);color:var(--text-primary);
  font:inherit;font-size:12.5px;cursor:pointer;
}
.clip-known-chip b{font-variant-numeric:tabular-nums}
.clip-known-chip .muted{font-variant-numeric:tabular-nums}
.clip-known-chip.is-win b{color:var(--ok)}
.clip-known-chip:hover{background:var(--surface-hover)}
.clip-known-chip.is-on{border-color:var(--accent);background:var(--surface-active)}
.clip-mv-match{padding:var(--space-4) 0;border-top:var(--border-hair) solid var(--border-subtle)}
.clip-results>.clip-mv-match:first-child{border-top:0}
.clip-mv-match-head{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3);
  margin-bottom:var(--space-2)}
.clip-mv-match-head b{font-size:15px;color:var(--text-primary)}
.clip-mv-match-head .tag.is-ok{color:var(--ok);border-color:var(--ok)}
.clip-mv-row{border-top:0;min-height:44px;padding:var(--space-2) 0}
.clip-mv-row .clip-res-rank{color:var(--accent)}
.clip-mv-row.is-failed .clip-res-rank{color:var(--warn)}
.clip-res-acts{display:flex;flex-wrap:wrap;gap:var(--space-2);justify-content:flex-end}
/* Watching a match video: only what is about the video stays on the panel. */
#clip-player-card.is-watch .clip-play-right>.panel:not(:first-child),
#clip-player-card.is-watch .clip-play-apply,
#clip-player-card.is-watch #clip-fx-timeline,
#clip-player-card.is-watch #clip-fx-stage{display:none!important}
.clip-mv-chapters{display:flex;flex-direction:column;align-items:flex-start;gap:2px}
.clip-mv-chapters .btn{justify-content:flex-start;height:auto;padding:4px 6px;text-align:left}
.clip-mv-chapters .mono{color:var(--accent);margin-right:6px}
"""

# Appended rather than inlined above so the clips-flow rules stay one
# readable block: the rail, the three reading choices and the calibration.
CSS = CSS + CLIPS_FLOW_CSS


REEL_CSS = """
/* ------------------------------------------------------------------ reels
   Five choices in order, each narrowing the next. The rail reports; it does
   not gate, because changing the song after picking moments should not send
   somebody back to the start. */
/* THE SONG EDIT, offered on the finished clips. The one animated button in
   the app: it appears once, at the moment somebody has just watched their
   clips, and it is the only thing on that card competing for attention. The
   sheen is a moving highlight rather than a colour cycle, so the button still
   reads as a button and still passes contrast at every frame. */
.clip-songedit{
  display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap;
  margin:var(--space-5) 0 0;
}
.clip-songedit .muted{margin:0}
.btn-flashy{
  position:relative;overflow:hidden;
  background:var(--accent);border-color:var(--accent);color:var(--text-on-accent);
  box-shadow:0 0 0 0 color-mix(in srgb, var(--accent) 55%, transparent);
  animation:as-flashy-pulse 2.6s var(--ease-standard) infinite;
}
.btn-flashy:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
.btn-flashy::after{
  content:"";position:absolute;inset:0;
  background:linear-gradient(115deg,transparent 30%,
             color-mix(in srgb, var(--text-on-accent) 45%, transparent) 50%,
             transparent 70%);
  transform:translateX(-120%);
  animation:as-flashy-sheen 2.6s var(--ease-standard) infinite;
}
@keyframes as-flashy-pulse{
  0%,100%{box-shadow:0 0 0 0 color-mix(in srgb, var(--accent) 55%, transparent)}
  50%{box-shadow:0 0 0 6px color-mix(in srgb, var(--accent) 0%, transparent)}
}
@keyframes as-flashy-sheen{
  0%{transform:translateX(-120%)}
  60%,100%{transform:translateX(120%)}
}
@media (prefers-reduced-motion:reduce){
  .btn-flashy{animation:none}
  .btn-flashy::after{animation:none;display:none}
}
/* The straight path through the reel maker. */
.reel-quick{display:flex;flex-direction:column;gap:var(--space-4)}
.reel-quick-msg{margin:0;color:var(--text-secondary);font-size:13.5px}
.reel-quick-msg.is-bad{color:var(--danger)}
.reel-quick-msg:empty{display:none}
.reel-quick-video{
  width:100%;max-height:56vh;display:block;border-radius:var(--radius-sm);
  background:#000;border:var(--border-hair) solid var(--border-subtle);
}
.reel-quick-ask{margin:var(--space-3) 0;font-weight:600}
.reel-steps{display:flex;flex-wrap:wrap;gap:6px;list-style:none;margin:0 0 4px;padding:0}
.reel-step-chip{
  padding:3px 10px;border-radius:999px;font-size:12px;
  border:var(--border-hair) solid var(--border-subtle);
  background:var(--surface);color:var(--text-secondary);
}
.reel-step-chip.is-done{border-color:var(--accent);color:var(--text-primary)}
.reel-step{
  padding-top:var(--space-5);margin-top:var(--space-5);
  border-top:var(--border-hair) solid var(--border-subtle);
}
.reel-h{font-size:13px;margin:0 0 var(--space-3);color:var(--text-secondary);
        text-transform:uppercase;letter-spacing:.04em}
.reel-wave{
  width:100%;height:120px;display:block;border-radius:var(--radius-sm);
  background:#0b0d11;cursor:crosshair;
  border:var(--border-hair) solid var(--border-subtle);
}
.reel-clock{font-variant-numeric:tabular-nums;font-size:18px;font-weight:600;
            min-width:92px}
/* One chip per mark, so a wrong beat in the middle of a run can go without
   clearing the ones after it. */
/* How the reel is ordered, and what is pinned where. Both sit with the bin's
   own controls: choosing the shape of a reel is the same kind of act as
   choosing its parts. */
.bin-arrange{display:inline-flex;gap:4px;flex-wrap:wrap;align-items:center}
.studio-pins{flex-wrap:wrap;gap:4px;margin:var(--space-2) 0}
.studio-pins .btn.is-active{
  border-color:var(--accent);color:var(--accent-text);background:var(--accent-muted);
}
.studio-pins .muted{font-size:11px}

/* The shaping dials: minus, name, plus. Inline with the bin's own buttons
   because shaping the reel is the same kind of act as picking its parts. */
.bin-shape{display:inline-flex;gap:8px;flex-wrap:wrap;align-items:center}
.shape-dial{
  display:inline-flex;align-items:center;gap:2px;
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-sm);
  padding:1px 2px;
}
.shape-dial b{
  font-size:11px;font-weight:600;color:var(--text-secondary);
  padding:0 5px;white-space:nowrap;
}
.shape-dial b i{font-style:normal;color:var(--accent);margin-left:5px}
.shape-dial.is-on{border-color:var(--accent)}
.shape-dial .btn{padding:1px 7px;min-width:0;line-height:1.4}

/* The star on a parts-bin card. Absolute inside the card button, so it never
   pushes the name or the example around, and always in the same corner. */
.bin-card{position:relative}
.bin-star{
  position:absolute;top:6px;right:7px;z-index:2;line-height:1;
  font-size:15px;color:var(--text-secondary);cursor:pointer;
  padding:2px 3px;border-radius:var(--radius-sm);
  background:color-mix(in srgb, var(--surface) 70%, transparent);
  opacity:0;transition:opacity .12s;
}
.bin-card:hover .bin-star,.bin-star:focus-visible{opacity:1}
.bin-star.is-on{opacity:1;color:var(--accent)}
.bin-star:hover{color:var(--accent)}
/* An effect's other versions open from its one card (asked 2026-10-17). */
.bin-more{display:inline-block;margin-top:6px;padding:2px 8px;border:1px solid var(--border-subtle);border-radius:999px;
  font-size:11px;color:var(--text-secondary);cursor:pointer}
.bin-more:hover,.bin-more:focus-visible{color:var(--accent);border-color:var(--accent)}
.bin-more.is-on{color:var(--accent);border-color:var(--accent)}
.bin-versions{margin-top:12px;padding:12px;border:1px solid var(--border-subtle);border-radius:var(--radius-md)}
.bin-versions h3{margin:0;font-size:13px}
.studio-fxp-back{margin:4px 0 8px}

.reel-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--space-3)}
.reel-chip{
  font-variant-numeric:tabular-nums;font-size:11px;padding:3px 8px;
  border-radius:var(--radius-sm);cursor:pointer;background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);
  color:var(--text-secondary);
}
/* A chip chooses a mark now rather than deleting it, so hover is an invitation
   rather than a warning -- Remove is its own button on the row that appears. */
.reel-chip:hover{border-color:var(--accent);color:var(--text-primary)}
.reel-chip.is-on{
  border-color:var(--accent);color:var(--text-primary);
  background:color-mix(in srgb, var(--accent) 14%, var(--surface));
}
/* The moments. A checkbox each, because "which of these" is the question and
   a grid of thumbnails would answer a different one. */
.reel-kills{display:grid;gap:6px;margin-top:var(--space-3)}
@media (min-width:760px){.reel-kills{grid-template-columns:repeat(3,1fr)}}
.reel-kill{
  display:flex;align-items:center;gap:8px;padding:6px 10px;font-size:12px;
  border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-sm);background:var(--surface);cursor:pointer;
}
.reel-kill:hover{background:var(--surface-hover)}
.reel-kill.is-on{border-color:var(--accent)}
.reel-kill-n{font-weight:600;color:var(--text-primary)}
.reel-kill-when{color:var(--text-secondary);font-variant-numeric:tabular-nums}
.reel-kill-lab{
  margin-left:auto;color:var(--accent);font-size:11px;
  text-transform:uppercase;letter-spacing:.03em;
}
.reel-templates{display:grid;gap:var(--space-3)}
@media (min-width:900px){.reel-templates{grid-template-columns:repeat(2,1fr)}}
.reel-tpl{
  display:flex;flex-direction:column;gap:4px;text-align:left;font:inherit;
  padding:var(--space-4);border-radius:var(--radius-md);cursor:pointer;
  border:var(--border-hair) solid var(--border-subtle);
  background:var(--surface);color:var(--text-secondary);
}
.reel-tpl:hover{background:var(--surface-hover)}
.reel-tpl.is-on{border-color:var(--accent);background:var(--surface-active)}
.reel-tpl b{color:var(--text-primary);font-size:14px}
.reel-tpl span{font-size:12px;line-height:1.45}
#reel-audio{width:100%;margin:var(--space-3) 0}
"""

# Appended so the reel rules stay one readable block.
CSS = CSS + REEL_CSS

STUDIO_CSS = r"""
/* In the card's foot, beside Play: over the thumbnail it would sit on top of
   the button that selects the clip. */
.studio-sg-songs{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--space-3)}
.studio-sg-song{max-width:320px;text-align:left;font-size:12.5px;padding:5px 10px;border-radius:999px;
  border:var(--border-hair) solid var(--border-subtle);background:var(--surface);color:var(--text-secondary);
  cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.studio-sg-song:hover{border-color:var(--border-strong);color:var(--text-primary)}
.studio-sg-song.is-on{border-color:var(--accent);background:var(--accent-muted);color:var(--text-primary)}
.studio-sg-viewbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin-top:var(--space-3)}
.studio-sg-toggles{display:flex;flex-wrap:wrap;gap:6px}
.studio-sg-toggle{font-size:12.5px;padding:4px 10px;border-radius:999px;cursor:pointer;
  border:var(--border-hair) solid var(--border-subtle);background:transparent;color:var(--text-secondary)}
.studio-sg-toggle[aria-pressed="true"]{background:var(--accent-muted);border-color:var(--accent);color:var(--text-primary)}
.studio-sg-lanes{border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md);
  overflow:hidden;background:var(--surface-sunken);margin-top:var(--space-3)}
.studio-sg-lane{position:relative;border-top:var(--border-hair) solid var(--border-subtle)}
.studio-sg-lane:first-child{border-top:0}
.studio-sg-lane canvas{display:block;width:100%;cursor:crosshair}
.studio-sg-lane .name{position:absolute;left:8px;top:5px;font-size:11px;color:var(--text-tertiary);
  background:var(--scrim);padding:1px 6px;border-radius:4px;pointer-events:none}

.studio-star{flex:none;width:26px;height:26px;line-height:1;display:flex;align-items:center;
  justify-content:center;font-size:15px;cursor:pointer;padding:0;border-radius:var(--radius-sm);
  border:var(--border-hair) solid transparent;background:transparent;color:var(--text-tertiary)}
.studio-star:hover{color:var(--warn);background:var(--surface-hover)}
.studio-star.is-on{color:var(--warn)}
.chip.studio-fav-chip:not(:disabled) b{color:var(--warn)}

/* ------------------------------------------------------------ parts bin */
/* The reel maker's front page. Every reel is one pick from each drawer, and
   each pick is shown by an example cut from the player's own clips, so a
   choice is made by watching rather than by reading a list of names. */
.bin-eyebrow{font:500 11px/1 var(--font-mono);letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent-text);margin:0}
.bin-top{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,1fr);gap:var(--space-6);
  align-items:start;padding-bottom:var(--space-5);border-bottom:2px solid var(--border-strong)}
@media (max-width:899px){.bin-top{grid-template-columns:1fr}}
.bin-intro{display:grid;gap:10px}
.bin-title{font-family:var(--font-condensed);font-weight:700;text-transform:uppercase;
  font-size:clamp(34px,5.2vw,58px);line-height:.95;letter-spacing:.005em;margin:0;color:var(--text-primary)}
.bin-lede{color:var(--text-secondary);max-width:62ch;margin:0;font-size:14.5px;line-height:1.55}
.bin-calc{background:var(--surface);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);padding:var(--space-4);display:grid;gap:10px}
.bin-big{font-family:var(--font-condensed);font-weight:700;font-size:clamp(30px,4vw,44px);line-height:1;
  color:var(--text-primary);font-variant-numeric:tabular-nums}
.bin-big small{display:block;margin-top:6px;font:500 12px/1.4 var(--font-mono);letter-spacing:0;
  color:var(--text-tertiary);text-transform:none}
.bin-slots{display:flex;flex-wrap:wrap;gap:6px}
.bin-slot{display:inline-flex;align-items:center;gap:7px;padding:4px 9px;cursor:pointer;font-size:12.5px;
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-sm);
  background:var(--surface-sunken);color:var(--text-secondary);user-select:none}
.bin-slot b{font:500 11px var(--font-mono);color:var(--text-tertiary)}
.bin-slot input{accent-color:var(--accent);margin:0}
.bin-slot:has(input:checked){border-color:var(--accent);background:var(--accent-muted);color:var(--text-primary)}

.bin-sec{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--space-4)}
.bin-sec-head{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px var(--space-5);align-items:end;
  border-bottom:2px solid var(--text-primary);padding-bottom:8px}
.bin-sec-head h2{font-family:var(--font-condensed);font-weight:700;text-transform:uppercase;margin:0;
  font-size:clamp(22px,2.6vw,30px);line-height:1;color:var(--text-primary)}
.bin-sec-head .count{font:500 11px var(--font-mono);letter-spacing:.08em;text-transform:uppercase;
  color:var(--text-tertiary);white-space:nowrap}
.bin-sec-head p{grid-column:1/-1;margin:0;color:var(--text-secondary);font-size:13.5px;max-width:78ch}
/* On a phone the nowrap count beside the heading was wider than the screen and
   pushed the whole drawer off its right edge; it goes under the heading there. */
@media (max-width:479px){
  .bin-sec-head{grid-template-columns:minmax(0,1fr)}
  .bin-sec-head .count{white-space:normal}
}

.bin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:var(--space-4)}
.bin-card{display:flex;flex-direction:column;gap:0;text-align:left;padding:0;cursor:pointer;font:inherit;
  background:var(--surface);color:var(--text-secondary);overflow:hidden;
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md)}
.bin-card:hover{border-color:var(--border-strong)}
.bin-card.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.bin-shot{position:relative;aspect-ratio:16/9;background:var(--surface-sunken);overflow:hidden}
.studio-pvplay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;cursor:pointer;
  color:var(--text-muted);font-size:20px;background:var(--surface-sunken)}
.studio-pvplay:hover,.studio-pvplay:focus-visible{color:var(--text-primary)}
.bin-shot video,.bin-shot img{width:100%;height:100%;object-fit:cover;display:block}
.bin-shot .bin-none{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:var(--text-tertiary);font:500 11px var(--font-mono);letter-spacing:.1em;text-transform:uppercase;
  text-align:center;padding:0 10px}
.bin-shot .bin-tag{position:absolute;left:6px;top:6px;padding:2px 6px;border-radius:4px;
  background:var(--scrim);color:var(--text-primary);font:500 10.5px var(--font-mono);letter-spacing:.06em}
.bin-shot .bin-sample{position:absolute;right:6px;bottom:6px;padding:1px 6px;border-radius:4px;
  background:var(--scrim);color:var(--text-secondary);font:500 10px var(--font-mono);letter-spacing:.08em;
  text-transform:uppercase}
.bin-meat{display:grid;gap:4px;padding:10px 11px 12px}
.bin-name{font-weight:600;color:var(--text-primary);font-size:13.5px;line-height:1.25}
.bin-blurb{font-size:12px;line-height:1.45;color:var(--text-secondary)}
.bin-card.is-on .bin-name{color:var(--accent-text)}

.bin-dealer{display:flex;flex-wrap:wrap;gap:var(--space-3);align-items:center}
.bin-code{font:500 12px var(--font-mono);color:var(--text-tertiary);letter-spacing:.08em}
.bin-hand{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:var(--space-3)}
/* A drawer's SET, under its card: the effects a reel draws from, each with how often. */
.studio-set{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}
.studio-set-chip{display:inline-flex;align-items:center;gap:2px;border:var(--border-hair) solid var(--border-strong);
  border-radius:999px;padding:2px 4px 2px 10px;background:var(--surface-2,var(--surface));font-size:12px}
.studio-set-name{margin-right:4px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.studio-set-w,.studio-set-x{border:0;background:transparent;color:var(--text-secondary);cursor:pointer;
  width:20px;height:20px;border-radius:50%;line-height:1;font-size:14px}
.studio-set-w:hover:not(:disabled),.studio-set-x:hover{background:var(--surface-3,rgba(255,255,255,.08));color:var(--text-primary)}
.studio-set-w:disabled{opacity:.3;cursor:default}
.studio-set-n{min-width:14px;text-align:center;font:600 12px var(--font-mono)}
.studio-set-sum{margin:4px 0 0}
.bin-drawer-label{font:500 10.5px var(--font-mono);letter-spacing:.1em;text-transform:uppercase;
  color:var(--text-tertiary)}
.bin-build{display:flex;flex-wrap:wrap;gap:var(--space-3);align-items:center;font-size:12.5px;
  color:var(--text-tertiary)}

/* ---------------------------------------------------------------- studio */
.studio{display:flex;flex-direction:column;gap:var(--space-6);padding-bottom:88px}
.studio-head{display:flex;flex-wrap:wrap;gap:var(--space-5);align-items:flex-end;justify-content:space-between}
.studio-title{font-family:var(--font-display);font-size:22px;font-weight:600;letter-spacing:-.012em;
  color:var(--text-primary);margin:0 0 4px}
.studio-h{font-size:13px;margin:var(--space-4) 0 var(--space-3);color:var(--text-secondary);
  text-transform:uppercase;letter-spacing:.04em}
.studio-tools{display:flex;flex-wrap:wrap;gap:var(--space-4);align-items:center}
.studio-search{max-width:320px;flex:1 1 220px}
.studio-games{display:flex;flex-wrap:wrap;gap:6px}
.studio-games .chip b{font-family:var(--font-mono);font-weight:500;opacity:.75}
.studio-reel-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:var(--space-4)}
.studio-reel{display:flex;flex-direction:column;gap:6px;padding:var(--space-4);background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md)}
.studio-reel-name{font-weight:600;color:var(--text-primary)}
.studio-reel-meta,.studio-reel-old{font-size:12px}
/* Delete sits at the far right of the card's action row, on whichever line it
   lands on: a card whose first button reads "Made before the Studio" wraps. */
.studio-reel .field-inline{flex-wrap:wrap;align-items:center}
.studio-reel .studio-del-btn{margin-left:auto}
/* The reels section: its own tools row, a grid of stills, folded to two rows. */
.studio-reels{display:flex;flex-direction:column;gap:var(--space-3);margin-top:var(--space-4)}
.studio-reels-head{display:flex;flex-wrap:wrap;gap:var(--space-3) var(--space-4);align-items:center}
.studio-reels-head .studio-h{margin:0;flex:0 0 auto}
.studio-reels-head .studio-h b{font-family:var(--font-mono);font-weight:500;opacity:.75}
.studio-reel-sortl{display:inline-flex;gap:6px;align-items:center;font-size:12px}
.studio-reels-more{align-self:flex-start}
.studio-reel{padding:var(--space-3)}
/* One frame shape for both orientations, so the grid stays a grid: a tall
   reel sits in the middle of it, letterboxed on the panel's own dark. */
.studio-reel-thumb{position:relative;display:block;width:100%;aspect-ratio:16/9;padding:0;border:0;cursor:pointer;
  border-radius:var(--radius-sm);overflow:hidden;background:var(--on-media-scrim)}
.studio-reel-thumb img{display:block;width:100%;height:100%;object-fit:cover}
.studio-reel-thumb.is-tall img{object-fit:contain}
.studio-reel-thumb:hover img{filter:brightness(1.08)}
.studio-reel-thumb:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.studio-reel-badge,.studio-reel-len{position:absolute;bottom:6px;font-family:var(--font-mono);font-size:11px;
  padding:1px 6px;border-radius:var(--radius-sm);background:var(--on-media-scrim);color:var(--on-media)}
.studio-reel-badge{left:6px}
.studio-reel-len{right:6px}
.studio-game-h{font-family:var(--font-display);font-size:18px;font-weight:600;color:var(--text-primary);
  margin:var(--space-6) 0 0;padding-bottom:6px;border-bottom:var(--border-hair) solid var(--border-subtle)}
.studio-folder{display:flex;flex-direction:column;gap:var(--space-3);margin-top:var(--space-5)}
.studio-folder-h{display:flex;flex-wrap:wrap;gap:var(--space-4);align-items:center}
.studio-folder-name{font-weight:600;color:var(--text-primary)}
/* THE LIBRARY AS A DRILL-DOWN: folders, then that folder's runs, then the
   run's clips under the match each came from. The alternative was 339 clip
   tiles in one pane, which is what this replaced. */
.studio-crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2);
  margin:var(--space-5) 0 var(--space-3);font-size:13px;color:var(--text-tertiary)}
.studio-crumb{padding:2px 6px;border:0;border-radius:var(--radius-sm);background:none;cursor:pointer;
  color:var(--text-secondary);font:inherit}
.studio-crumb:hover{color:var(--text-primary);background:var(--surface-hover)}
.studio-crumb:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.studio-crumb-now{color:var(--text-primary);font-weight:600}
.studio-folders{display:grid;grid-template-columns:repeat(auto-fill,minmax(248px,1fr));
  gap:var(--space-4);margin-top:var(--space-4)}
.studio-folder-card{display:block;padding:0;text-align:left;cursor:pointer;color:inherit;font:inherit;
  background:var(--surface);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-lg);overflow:hidden;
  transition:border-color var(--dur-instant),box-shadow var(--dur-instant)}
.studio-folder-card:hover{border-color:var(--border-strong);box-shadow:var(--shadow-md);z-index:calc(var(--z-topbar) + 1)}
.studio-folder-card:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.studio-folder-card[disabled]{opacity:var(--opacity-disabled);cursor:default}
.studio-folder-mosaic{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:2px;
  aspect-ratio:16/9;background:var(--surface-sunken);overflow:hidden}
.studio-folder-mosaic img{display:block;width:100%;height:100%;object-fit:cover}
.studio-folder-star{display:grid;place-items:center;font-size:40px;color:var(--text-tertiary)}
.studio-folder-card-body{display:block;padding:var(--space-3) var(--space-4) var(--space-4)}
.studio-folder-card-name{display:block;font-family:var(--font-display);font-size:15px;font-weight:600;
  color:var(--text-primary)}
.studio-folder-card-facts{display:block;margin-top:5px;font-size:12.5px;color:var(--text-tertiary)}
.studio-folder-go{display:block;margin-top:var(--space-3);font-size:12.5px;color:var(--accent-text)}
.studio-runs{display:flex;flex-direction:column;gap:var(--space-3);margin-top:var(--space-4)}
.studio-run{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3);
  background:var(--surface);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);padding:var(--space-2) var(--space-4) var(--space-2) var(--space-2)}
.studio-run:hover{border-color:var(--border-strong)}
.studio-run-hit{display:flex;align-items:center;gap:var(--space-4);flex:1;min-width:240px;
  padding:0;border:0;background:none;cursor:pointer;text-align:left;color:inherit;font:inherit}
.studio-run-hit:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.studio-run-shot{width:112px;height:63px;flex:0 0 auto;object-fit:cover;border-radius:var(--radius-sm);
  background:var(--surface-sunken)}
.studio-run-who{display:flex;flex-direction:column;gap:4px;min-width:0}
.studio-run-name{font-family:var(--font-display);font-size:14.5px;font-weight:600;color:var(--text-primary)}
.studio-run-facts{font-size:12.5px;color:var(--text-tertiary)}
.studio-run-acts{display:flex;align-items:center;gap:var(--space-2);margin-left:auto}
.studio-run-head{margin-top:var(--space-5)}
.studio-run-head .studio-game-h{margin:0;border:0;padding:0}
.studio-mchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}
.studio-mchip{font-size:11.5px;padding:2px 9px;border-radius:var(--radius-pill);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);
  color:var(--text-secondary)}
/* Won and lost are read at a glance here and are never the accent: the accent
   budget is the focus ring, the rail, the primary button and an on state. */
.studio-mchip.is-win,.studio-match-score.is-win{color:var(--ok);border-color:var(--ok)}
.studio-mchip.is-loss,.studio-match-score.is-loss{color:var(--danger);border-color:var(--danger)}
.studio-match{display:flex;flex-direction:column;gap:var(--space-3);margin-top:var(--space-5)}
.studio-match-h{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3) var(--space-4);
  padding:var(--space-2) var(--space-4);background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md)}
.studio-match-name{font-family:var(--font-display);font-size:14.5px;font-weight:600;color:var(--text-primary)}
.studio-match-score{font-size:13px;font-weight:600;padding:2px 8px;border-radius:var(--radius-sm);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle)}
.studio-match-btn{margin-left:auto}
/* WHERE THE PICKED CLIPS ARE. A pill on every level that hides clips behind
   a click, and -- while adding to a reel -- a band naming the runs they came
   from. The complaint this answers: "I don't know from which folder, from
   which run the current clips are selected". */
.studio-picked{margin-left:8px;padding:1px 9px;border-radius:var(--radius-pill);
  background:var(--accent);color:var(--text-on-accent);
  font-family:var(--font-text);font-size:11px;font-weight:600;white-space:nowrap}
.studio-band{display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap;
  margin-top:var(--space-4);padding:var(--space-3) var(--space-4);
  background:var(--surface);border:var(--border-hair) solid var(--accent);
  border-radius:var(--radius-lg)}
.studio-band-who{display:flex;flex-direction:column;gap:3px;min-width:160px}
.studio-band-runs{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1;min-width:200px}
.studio-band-acts{display:flex;align-items:center;gap:var(--space-2);margin-left:auto}
.studio-srcchip{cursor:pointer}
.studio-srcchip b{font-family:var(--font-mono);font-weight:600;margin-left:4px;color:var(--text-primary)}
.studio-tray-runs{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
/* THE ORDER, IN THE MAKE DIALOG. Cards, not a segmented row: "Best order"
   and "Perfect fit" are choices nobody can make from two words, which is
   why they went unseen in the strip at the foot of the page. */
.studio-mk-arrange{display:grid;grid-template-columns:repeat(auto-fit,minmax(248px,1fr));
  gap:var(--space-3);margin:var(--space-3) 0 var(--space-5)}
.studio-mk-arr{display:flex;flex-direction:column;gap:5px;text-align:left;cursor:pointer;
  padding:var(--space-3) var(--space-4);border-radius:var(--radius-md);
  background:var(--surface);border:var(--border-hair) solid var(--border-subtle);
  color:inherit;font:inherit;transition:border-color var(--dur-instant),box-shadow var(--dur-instant)}
.studio-mk-arr:hover{border-color:var(--border-strong)}
.studio-mk-arr:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.studio-mk-arr.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);
  background:var(--surface-raised)}
.studio-mk-arr-name{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  font-family:var(--font-display);font-size:14px;font-weight:600;color:var(--text-primary)}
.studio-mk-arr-note{padding:1px 8px;border-radius:var(--radius-pill);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);
  color:var(--text-secondary);font-family:var(--font-text);font-size:11px;font-weight:600}
.studio-mk-arr-why{color:var(--text-tertiary);font-size:12px;line-height:1.45}
.studio-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:var(--space-4)}
.studio-clip{position:relative;display:flex;flex-direction:column;background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md);overflow:hidden;
  transition:border-color var(--dur-instant),box-shadow var(--dur-instant)}
.studio-clip:hover{border-color:var(--border-strong)}
.studio-clip.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.studio-clip-hit{position:relative;display:block;padding:0;border:0;background:#000;cursor:pointer;
  aspect-ratio:16/9;width:100%}
.studio-clip-hit img{display:block;width:100%;height:100%;object-fit:cover}
.studio-clip-n{position:absolute;top:8px;left:8px;min-width:24px;height:24px;padding:0 6px;border-radius:12px;
  display:flex;align-items:center;justify-content:center;font:600 12px/1 var(--font-mono);
  background:var(--on-media-scrim-soft);color:var(--on-media);border:2px solid rgba(255,255,255,.75)}
.studio-clip.is-on .studio-clip-n{background:var(--accent);border-color:var(--accent);color:var(--text-on-accent)}
.studio-clip-dur,.studio-clip-kills{position:absolute;bottom:6px;padding:2px 6px;border-radius:4px;
  background:var(--on-media-scrim);color:var(--on-media);font-size:11px}
.studio-clip-dur{right:6px}
.studio-clip-kills{left:6px;font-weight:600}
.studio-clip-foot{display:flex;align-items:center;gap:6px;padding:4px 4px 4px 10px;font-size:12.5px;
  color:var(--text-secondary);min-width:0}
.studio-clip-foot .truncate{flex:1;min-width:0}
.studio-empty{padding:var(--space-8) 0}
.studio-tray{position:sticky;bottom:var(--space-4);z-index:var(--z-sticky);display:flex;flex-wrap:wrap;
  align-items:center;gap:var(--space-4);margin-top:var(--space-6);padding:var(--space-4) var(--space-5);
  background:var(--surface-raised);border:var(--border-hair) solid var(--border-strong);
  border-radius:var(--radius-lg);box-shadow:var(--shadow-lg)}
.studio-tray-text{display:flex;flex-direction:column;flex:1;min-width:160px}
.studio-modal{width:min(820px,100%);max-height:calc(100vh - 48px);overflow:auto}
.studio-modal .modal-body{max-width:none}
.studio-modal .modal-actions{position:sticky;bottom:calc(-1 * var(--space-8));margin:0 calc(-1 * var(--space-8)) calc(-1 * var(--space-8));
  padding:var(--space-5) var(--space-8);background:var(--surface-overlay);
  border-top:var(--border-hair) solid var(--border-subtle);align-items:center}
.studio-modal .modal-actions .muted{margin-right:auto}
.studio-modal video{width:100%;max-height:60vh;background:#000;border-radius:var(--radius-sm)}
.studio-styles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:var(--space-4)}
.studio-style{display:flex;flex-direction:column;gap:6px;text-align:left;padding:var(--space-4);cursor:pointer;
  background:var(--surface);color:var(--text-secondary);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);font:inherit}
.studio-style:hover{border-color:var(--border-strong)}
/* THE MAKE PAGE: a page in the Studio's own flow, not a dialog over it. While it is open the rest of
   the Studio steps aside. */
.scrim.studio-page{position:static;display:block;padding:0;background:none;animation:none;z-index:auto}
.scrim.studio-page.hide{display:none}
#view-studio.is-making .studio > :not(.scrim){display:none}
/* AS WIDE AS THE WINDOW. The page sat in a 1180 px column inside the app's 1280 px reading width, so
   on a 2560 px screen a third of it was empty on either side while eleven style cards wrapped onto
   three rows and fifty kill marks crowded one short waveform. A page of pictures and timelines is not
   a page of prose: it takes the width, with a ceiling only where a line would get too long to follow. */
#view-studio.is-making{max-width:none}

/* THE GUIDED MAKER: one question a screen, the match chip pinned under it. */
.studio-gd{max-width:1100px}
.gd-steps{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:var(--space-2)}
.gd-step{width:100%;display:grid;gap:2px;text-align:left;padding:var(--space-2) var(--space-3);background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);cursor:pointer;min-width:0}
.gd-step b{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-tertiary)}
.gd-step span{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gd-step.is-on{border-color:var(--accent)}.gd-step.is-on b{color:var(--accent)}
.gd-step.is-done span::after{content:" \2713";color:var(--ok)}
.gd-step:disabled{opacity:.45;cursor:default}
.gd-body{display:grid;gap:var(--space-4);min-width:0}
.gd-q h3{margin:0 0 4px;font-size:20px}.gd-q p{margin:0}
.gd-auto{display:grid;gap:4px;text-align:left;padding:var(--space-3) var(--space-4);border:1px dashed var(--accent);border-radius:var(--radius-md);background:var(--surface);cursor:pointer}
.gd-auto.is-on{background:var(--surface-active)}
.gd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:var(--space-3)}
.gd-grid-best{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.gd-card,.gd-clip{display:grid;gap:6px;align-content:start;text-align:left;padding:var(--space-3);background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);cursor:pointer;min-width:0}
.gd-card:hover,.gd-clip:hover{border-color:var(--border-strong)}
.gd-card.is-on,.gd-clip.is-on{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.gd-card video{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:var(--radius-sm);background:#000}
.gd-card-name{font-weight:600;display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline}
.gd-best{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.gd-more summary{cursor:pointer;font-weight:600}
.gd-more .gd-grid{margin-top:var(--space-3)}
.gd-note{margin:0;color:var(--warn)}
.gd-facts{display:flex;flex-wrap:wrap;gap:var(--space-2) var(--space-5)}
.gd-facts b{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-tertiary);margin-right:6px}
.gd-slot{display:grid;gap:var(--space-3)}
.gd-slothead{display:flex;justify-content:space-between;gap:var(--space-3);align-items:baseline}.gd-slothead h4,.gd-field h4{margin:0}
.gd-bar{height:8px;border-radius:4px;background:var(--surface-active);border:1px solid var(--border);overflow:hidden}.gd-bar i{display:block;height:100%;background:var(--accent)}
.gd-tags{display:flex;flex-wrap:wrap;gap:4px}.gd-tags i{font-size:10.5px;font-weight:600;font-style:normal;letter-spacing:.06em;text-transform:uppercase;padding:2px 6px;border:1px solid var(--border);border-radius:3px;color:var(--text-secondary)}
.gd-tags .gd-hs{color:var(--warn)}.gd-tags .gd-fav{color:var(--accent)}
/* EACH SLOT'S CLIP BROWSER: find, filters and sort above, a page of thumbnail cards, the pager below. */
.gd-browse{display:grid;gap:var(--space-3);min-width:0}
.gd-results{display:grid;gap:var(--space-3);min-width:0}
.gd-tools{display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center}.gd-tools .input{flex:1 1 220px;min-width:0;max-width:360px}
.gd-tools .select{flex:0 1 auto;min-width:0;max-width:240px}
.gd-tools .btn[aria-pressed="true"]{border-color:var(--accent);color:var(--accent)}
.gd-count{margin:0;font-size:12px}
.gd-clips{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.gd-clip{padding:0;gap:0;overflow:hidden;cursor:default}
.gd-clip-hit{display:grid;gap:6px;align-content:start;min-width:0;padding:0 0 var(--space-2);text-align:left;background:none;border:0;color:inherit;font:inherit;cursor:pointer}
.gd-clip-hit>:not(.gd-thumb){margin:0 var(--space-3)}
.gd-clip-hit:focus-visible{outline:var(--focus-ring-width) solid var(--accent);outline-offset:calc(-1 * var(--focus-ring-width))}
.gd-thumb{position:relative;display:block;aspect-ratio:16/9;background:var(--surface-active);overflow:hidden}
.gd-thumb img{display:block;width:100%;height:100%;object-fit:cover}
.gd-thumb.is-missing img{visibility:hidden}
.gd-len{position:absolute;right:6px;bottom:6px;padding:1px 6px;border-radius:var(--radius-sm);font-size:11px;background:var(--on-media-scrim);color:var(--on-media)}
.gd-tick{position:absolute;left:6px;top:6px;display:none;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--accent);color:var(--text-on-accent)}
.gd-tick .icon{width:16px;height:16px}
.gd-clip.is-on .gd-tick{display:grid}
.gd-name{font-size:12px;overflow-wrap:anywhere}
/* THE DECLUTTERED CLIPS STEP: what a card is, laid over its frame; one line under it; the rest behind "..." */
.gd-thumb .gd-tags{position:absolute;left:6px;right:44px;bottom:6px;flex-wrap:wrap}
.gd-thumb .gd-tags i{background:var(--on-media-scrim);color:var(--on-media);border-color:transparent}
.gd-thumb .gd-tags .gd-hs{color:#ffd27a}.gd-thumb .gd-tags .gd-fav{color:#ffd27a}
.gd-clip.is-on .gd-tick{display:grid}
.gd-cap{display:grid;gap:2px;min-width:0;padding-top:2px}
.gd-lab{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gd-cap .gd-meta{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gd-clip-acts{align-items:center}
.gd-info{position:relative;margin-left:auto}
.gd-info summary{list-style:none;cursor:pointer;padding:2px 10px;border-radius:var(--radius-sm);color:var(--text-secondary)}
.gd-info summary::-webkit-details-marker{display:none}
.gd-info summary:hover{background:var(--surface-hover,var(--surface-active))}
.gd-info[open]{flex-basis:100%;display:grid;gap:6px}
.gd-info[open] summary{justify-self:end}
.gd-sum{position:sticky;top:0;z-index:3;display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3) var(--space-5);
  padding:var(--space-3) var(--space-4);border:var(--border-hair) solid var(--border);border-radius:var(--radius-md);
  background:var(--surface-raised,var(--surface));box-shadow:var(--shadow-sm,none)}
.gd-sumbuild{display:flex;align-items:center;gap:var(--space-2)}
.gd-sumbuild b,.gd-tray b{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-tertiary);margin-right:4px}
.gd-sumthumb{width:64px;aspect-ratio:16/9;object-fit:cover;border-radius:var(--radius-sm);background:#000}
.gd-sumcount{flex:1 1 260px;display:grid;gap:6px;min-width:0}
.gd-strip{grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.gd-chipbtn{padding:5px 12px;border:var(--border-hair) solid var(--border);border-radius:999px;background:var(--surface);color:var(--text-secondary);
  font:inherit;font-size:13px;cursor:pointer;white-space:nowrap}
.gd-chipbtn:hover{border-color:var(--border-strong)}
.gd-chipbtn[aria-pressed="true"],.gd-chipbtn.is-active{border-color:var(--accent);color:var(--accent);background:var(--accent-muted)}
.gd-filters{position:relative}
.gd-filters summary{list-style:none;cursor:pointer;padding:5px 12px;border:var(--border-hair) solid var(--border);border-radius:999px;font-size:13px;color:var(--text-secondary)}
.gd-filters summary::-webkit-details-marker{display:none}
.gd-filters[open] summary{border-color:var(--accent);color:var(--accent)}
.gd-filterbox{position:absolute;z-index:5;top:calc(100% + 6px);left:0;display:grid;gap:var(--space-2);min-width:280px;padding:var(--space-3);
  border:var(--border-hair) solid var(--border);border-radius:var(--radius-md);background:var(--surface-raised,var(--surface));box-shadow:var(--shadow-md)}
.gd-filter{display:grid;grid-template-columns:6.5em minmax(0,1fr);align-items:center;gap:var(--space-2);font-size:13px;color:var(--text-secondary)}
.gd-filter .select{max-width:none;width:100%}
.gd-tools .gd-sort{margin-left:auto}
.gd-counts{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2) var(--space-3)}
.gd-active{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.gd-moreclips{display:flex;flex-wrap:wrap;gap:var(--space-3);align-items:center;justify-content:center}
.gd-tray{position:sticky;bottom:0;z-index:3;display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2) var(--space-3);
  padding:var(--space-2) var(--space-4);border:var(--border-hair) solid var(--border);border-radius:var(--radius-md);
  background:var(--surface-raised,var(--surface));box-shadow:var(--shadow-md)}
.gd-traythumbs{display:flex;flex-wrap:wrap;gap:4px;align-items:center;flex:1 1 auto;min-width:0}
.gd-trayclip{padding:0;border:2px solid transparent;border-radius:3px;background:none;cursor:pointer;line-height:0}
.gd-trayclip img{width:48px;aspect-ratio:16/9;object-fit:cover;border-radius:2px;background:#000}
.gd-trayclip.is-build{border-color:var(--warn)}
.gd-trayclip:hover{border-color:var(--danger)}
.gd-timing{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2) var(--space-3)}
.seg-sm .seg-btn{padding:3px 10px;font-size:12.5px}
.gd-kept{margin:0;font-size:12.5px}
.gd-timing b{font-weight:600}
.gd-lensecs{width:90px}
.gd-meta{font-size:12px;color:var(--text-tertiary);overflow-wrap:anywhere}
.gd-clip-acts{display:flex;flex-wrap:wrap;gap:var(--space-2);padding:0 var(--space-3) var(--space-3)}
.gd-clip-acts .icon{width:14px;height:14px}
.gd-pager{display:flex;flex-wrap:wrap;gap:4px;align-items:center;justify-content:center}
.gd-gap{padding:0 4px;color:var(--text-tertiary)}
/* The preview's kills along the clip, and where it is playing. */
.gd-pvmarks{position:relative;height:18px;margin-top:var(--space-2);border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface-active)}
.gd-pvmark{position:absolute;top:2px;bottom:2px;width:6px;margin-left:-3px;padding:0;border:0;border-radius:2px;background:var(--text-secondary);cursor:pointer}
.gd-pvmark.is-hs{background:var(--warn)}
.gd-pvhead{position:absolute;top:0;bottom:0;left:0;width:2px;background:var(--accent);pointer-events:none}
/* The Clips page's player visited from the guide (clip_visit): the player alone. */
#view-clips.is-visit>:not(#clip-player-card){display:none!important}
#view-clips.is-visit>#clip-player-card:not(.hide){display:flex!important}
.gd-field{display:grid;gap:var(--space-2)}
/* Chosen clips the style cannot use, each with why: in the draft, out of the counts and the plan. */
.gd-left{border:1px dashed var(--border-strong);border-radius:var(--radius-md);padding:var(--space-3)}
.gd-leftlist,.gd-why{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.gd-leftlist li{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px var(--space-3)}
.gd-why li{color:var(--text-secondary)}.gd-why b{color:var(--text-primary)}
.gd-acts{display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center}
/* THE SONG STEP'S DROPS: the song drawn, a small player, the drops as a list to play into and change. */
.gd-dropbox{position:relative;width:100%;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface-sunken,var(--surface));overflow:hidden}
.gd-dropbox canvas{display:block;width:100%;height:150px;cursor:crosshair;touch-action:none}
.gd-transport{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2) var(--space-3)}
.gd-time{min-width:96px;text-align:center}
.gd-seek{flex:1 1 220px;min-width:140px;accent-color:var(--accent)}
.gd-vol{display:inline-flex;align-items:center;gap:6px}.gd-vol input{width:96px;accent-color:var(--accent)}
.gd-snap{display:inline-flex;align-items:center;gap:6px;color:var(--text-secondary)}
.gd-droplist{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.gd-droprow{display:grid;grid-template-columns:3em 6em 8em 7em minmax(0,1fr);align-items:center;gap:var(--space-2);padding:2px 0;border-bottom:1px solid var(--border-subtle)}
.gd-droprow.is-hand .gd-who{color:var(--warn)}
.gd-who{color:var(--text-tertiary)}
.gd-main{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--warn)}
.gd-droptools{display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end}
@media (max-width:639px){.gd-droprow{grid-template-columns:3em 6em minmax(0,1fr)}.gd-droprow .gd-who,.gd-droprow .gd-main{display:none}}
.gd-partrow{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--space-2)}
.gd-howlong{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:var(--space-2)}
@media (max-width:1119px){.gd-howlong{grid-template-columns:repeat(3,minmax(0,1fr))}}
.gd-lenopt{display:flex;flex-direction:column;align-items:flex-start;gap:2px;padding:var(--space-2) var(--space-3);
  border:var(--border-hair) solid var(--border);border-radius:var(--radius-md);background:var(--surface);color:var(--text-primary);
  font:inherit;text-align:left;cursor:pointer}
.gd-lenopt:hover{border-color:var(--border-strong)}
.gd-lenopt.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);background:var(--accent-muted)}
.gd-lenopt span{font-size:12px}
.gd-marklist{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.gd-marklist li{display:grid;grid-template-columns:3em 6em minmax(0,1fr);align-items:center;gap:var(--space-2);border-bottom:1px solid var(--border-subtle)}
@media (max-width:639px){.gd-howlong{grid-template-columns:1fr}}
/* THE LOOK STEP: the 9:16 preview beside its controls, the band and what is behind it drawn as the
   render draws them (studio.frame_settings, studio._bg_graph) */
.lk-wrap{display:grid;grid-template-columns:minmax(220px,300px) minmax(0,1fr);gap:var(--space-5);align-items:start}
.lk-wrap.is-wide{grid-template-columns:minmax(0,1fr)}
.lk-left{position:sticky;top:0;display:grid;gap:var(--space-2)}
.lk-right{display:grid;gap:var(--space-4);min-width:0}
.lk-pv{position:relative;width:100%;aspect-ratio:9/16;border-radius:var(--radius-md);overflow:hidden;background:#000;
  border:var(--border-hair) solid var(--border)}
.lk-back{position:absolute;inset:0;overflow:hidden}
.lk-back video,.lk-back img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transform:scale(1.12)}
.lk-band{position:absolute;left:0;right:0;overflow:hidden;display:grid;place-items:center}
.lk-band video{width:100%;height:100%;object-fit:cover}
.lk-says{margin:0;font-size:12px}
.lk-range{display:grid;grid-template-columns:7.5em minmax(0,1fr);align-items:center;gap:var(--space-3);max-width:520px}
.lk-range span{color:var(--text-secondary);font-size:13px}
.lk-range input[type=range]{accent-color:var(--accent);width:100%}
.lk-range input[type=color]{width:48px;height:28px;padding:0;border:var(--border-hair) solid var(--border);border-radius:var(--radius-sm);background:none}
.lk-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:var(--space-2);max-height:300px;overflow:auto;padding:2px}
.lk-tile{display:grid;gap:4px;padding:4px;border:var(--border-hair) solid var(--border);border-radius:var(--radius-sm);background:var(--surface);
  color:var(--text-secondary);font:inherit;font-size:11px;text-align:left;cursor:pointer;min-width:0}
.lk-tile video,.lk-tile img{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:2px;background:#000}
.lk-tile span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lk-tile.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
@media (max-width:759px){.lk-wrap{grid-template-columns:minmax(0,1fr)}.lk-left{position:static;max-width:260px}}
.gd-chip{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:var(--space-3);padding:var(--space-3) var(--space-4);border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface)}
.gd-chip p{margin:0;min-width:0}
.gd-dot{font-size:12px;font-weight:700;letter-spacing:.05em;padding:3px 8px;border-radius:4px;text-transform:uppercase;white-space:nowrap}
.gd-chip.ok .gd-dot{color:var(--ok)}.gd-chip.warn{border-color:var(--warn)}.gd-chip.warn .gd-dot{color:var(--warn)}
.gd-chip.bad{border-color:var(--bad)}.gd-chip.bad .gd-dot{color:var(--bad)}
.gd-foot{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:var(--space-3)}
.gd-nav{display:flex;gap:var(--space-2)}
@media (max-width:639px){.gd-chip{grid-template-columns:minmax(0,1fr)}}
.studio-page-card{display:flex;flex-direction:column;gap:var(--space-5);width:100%;max-width:2200px;margin:0 auto}
.mk-head{display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap}
.mk-title{margin:0;font-size:22px}
.mk-layout{display:grid;grid-template-columns:160px minmax(0,1fr);gap:var(--space-7,40px);align-items:start}
.mk-head-text .muted{max-width:90ch}
.mk-nav{position:sticky;top:var(--space-4);display:flex;flex-direction:column;gap:4px}
.mk-nav-b{text-align:left;padding:8px 12px;border:0;border-left:2px solid var(--border-subtle);background:transparent;
  color:var(--text-secondary);font:inherit;cursor:pointer}
.mk-nav-b:hover{color:var(--text-primary)}
.mk-nav-b.is-on{border-left-color:var(--accent);color:var(--text-primary);font-weight:600}
.mk-body{display:flex;flex-direction:column;gap:var(--space-7,40px);min-width:0}
.mk-sec{scroll-margin-top:var(--space-4);display:flex;flex-direction:column;gap:var(--space-3)}
.mk-bar{position:sticky;bottom:0;display:flex;align-items:center;justify-content:flex-end;gap:var(--space-3);
  padding:var(--space-3) var(--space-4);background:var(--surface);border-top:var(--border-hair) solid var(--border-subtle);
  z-index:2}
.mk-bar .muted{margin-right:auto}
@media (max-width:759px){.mk-layout{grid-template-columns:minmax(0,1fr)}
  .mk-nav{position:static;flex-direction:row;flex-wrap:wrap}
  .mk-nav-b{border-left:0;border-bottom:2px solid var(--border-subtle)}
  .mk-nav-b.is-on{border-bottom-color:var(--accent)}}
/* STYLE CARDS: each plays about twenty seconds cut from the player's own kills. */
.studio-samples-bar{display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap}
.studio-style-card{display:flex;flex-direction:column;gap:var(--space-2);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);background:var(--surface);overflow:hidden}
.studio-style-card.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.studio-style-card .studio-style{border:0;border-radius:0;background:transparent;box-shadow:none}
.studio-style-media{position:relative;aspect-ratio:16/9;background:var(--surface-sunken);display:flex;align-items:center;justify-content:center}
.studio-style-own{position:absolute;left:8px;top:8px;font-size:10.5px;font-weight:600;padding:2px 7px;border-radius:99px;
  background:var(--on-media-scrim);color:var(--on-media)}
.studio-style-media video{width:100%;height:100%;object-fit:cover;display:block}
.studio-style-none{font-size:12px;color:var(--text-tertiary);padding:var(--space-3);text-align:center}
.studio-style-tag{font-size:10px;font-weight:500;padding:1px 6px;border-radius:99px;border:var(--border-hair) solid var(--border-strong);
  color:var(--text-secondary);vertical-align:middle}
.studio-style-more{padding:0 var(--space-4) var(--space-3);font-size:11px;color:var(--text-tertiary)}
.studio-style-more summary{cursor:pointer}
/* THE KILLS ON THE SONG */
.studio-mk-kills{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-mk-kills canvas{touch-action:none;cursor:crosshair}
.studio-mk-marklist{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:4px 16px}
.studio-mk-markrow{display:flex;align-items:center;gap:var(--space-3);font-size:12.5px;min-width:0}
.studio-mk-markrow.is-hand .studio-mk-markpick .mono{color:var(--accent)}
.studio-mk-markrow.is-auto .studio-mk-markpick .mono{color:var(--ok)}
.studio-mk-markrow.is-drop .studio-mk-markpick .mono{color:var(--warn)}
.studio-mk-markrow.is-sel{background:var(--surface-active);border-radius:var(--radius-sm)}
.studio-mk-markpick{display:inline-flex;align-items:center;gap:6px;cursor:pointer;min-width:52px}
.studio-mk-who{font-size:11px;color:var(--text-tertiary);min-width:34px}
.studio-mk-droplist:empty{display:none}
.studio-mk-droplist{padding-bottom:var(--space-2);border-bottom:var(--border-hair) solid var(--border-subtle)}
.studio-mk-selbar{gap:var(--space-3)}
.studio-mk-legend{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2) var(--space-5);font-size:12px;color:var(--text-secondary)}
.studio-mk-legend > span{display:inline-flex;align-items:center;gap:6px}
.studio-mk-legend .studio-check:first-of-type{margin-left:auto}
.mk-key{display:inline-block;width:10px;height:10px;transform:rotate(45deg);box-sizing:border-box}
.mk-key-auto{border:1.5px solid var(--ok);background:var(--surface)}
.mk-key-hand{background:var(--accent)}
.mk-key-dropauto,.mk-key-drophand{transform:none;width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;
  border-top:10px solid var(--warn)}
.mk-key-dropauto{opacity:.55}
.studio-mk-markname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.studio-mk-marktools{display:inline-flex;gap:2px}

.studio-style.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.studio-style-name{font-weight:600;color:var(--text-primary)}
.studio-style-blurb{font-size:12.5px;line-height:1.45}
.studio-style-data{font-size:11px;color:var(--text-tertiary)}
.studio-shape{gap:var(--space-4)}

.studio-top{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(260px,1fr);gap:var(--space-5);align-items:start}
@media (max-width:979px){.studio-top{grid-template-columns:1fr}}
.studio-player{position:relative;background:#000;border-radius:var(--radius-md);overflow:hidden;
  aspect-ratio:16/9;display:flex;align-items:center;justify-content:center}
.studio-player video{width:100%;height:100%;object-fit:contain;background:#000}
.studio-player-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:#c8ccd4;font-size:14px;padding:var(--space-6);text-align:center}
.studio-render .card-body{display:flex;flex-direction:column;gap:var(--space-5)}
.studio-facts{font-size:12.5px;margin:0}

/* IS THE VIDEO WHAT I EDITED? One plate answers it, and the plate is the only
   status colour on the page: the timeline is full of accent already, so the
   answer had to be a shape and a colour the timeline never uses. */
.studio-sync{display:flex;flex-direction:column;gap:var(--space-3);
  padding:var(--space-5);border-radius:var(--radius-sm);
  border:var(--border-hair) solid var(--border-subtle);border-left-width:3px;
  background:var(--surface-sunken)}
.studio-sync-line{display:flex;align-items:center;gap:var(--space-4);margin:0}
.studio-sync-dot{flex:none;width:var(--size-dot);height:var(--size-dot);border-radius:var(--radius-pill);
  background:var(--text-tertiary)}
.studio-sync-head{font:600 13.5px/1.35 var(--font-text);color:var(--text-primary)}
.studio-sync-sub{margin:0;font-size:12.5px;color:var(--text-secondary)}
.studio-state{font-size:12.5px;color:var(--text-secondary);min-height:1.35em;margin:0}
.studio-state.is-bad{color:var(--danger);white-space:pre-wrap}
.studio-sync.is-ok{border-left-color:var(--ok);background:var(--ok-muted)}
.studio-sync.is-ok .studio-sync-dot{background:var(--ok)}
.studio-sync.is-stale{border-left-color:var(--warn);background:var(--warn-muted)}
.studio-sync.is-stale .studio-sync-dot{background:var(--warn)}
.studio-sync.is-bad{border-left-color:var(--danger);background:var(--danger-muted)}
.studio-sync.is-bad .studio-sync-dot{background:var(--danger)}
/* The meter is the progress; the dot would only pulse next to it. */
.studio-sync.is-busy{border-left-color:var(--text-tertiary)}

/* WHICH changes, not just how many. Kept to the width of the card and to six
   lines, because a list long enough to scroll is the clutter it replaced. */
.studio-pending{list-style:none;margin:0;padding:var(--space-3) 0 0;
  border-top:var(--border-hair) solid var(--border-subtle);
  display:flex;flex-direction:column;gap:var(--space-2)}
.studio-pending li{display:flex;align-items:baseline;gap:var(--space-3);font-size:12.5px;
  color:var(--text-primary);overflow-wrap:anywhere}
.studio-pending li::before{content:"";flex:none;width:3px;height:3px;margin-top:6px;border-radius:var(--radius-pill);
  background:var(--warn)}
.studio-sync.is-bad .studio-pending li::before{background:var(--danger)}
.studio-pending-more{color:var(--text-tertiary)}
.studio-pending-more::before{background:var(--border-strong) !important}

/* The badge over the video itself. Someone watching the player is not reading
   the sidebar, and this is the one place they cannot miss. */
.studio-stale{position:absolute;top:var(--space-5);left:var(--space-5);z-index:1;
  padding:var(--space-3) var(--space-5);border-radius:var(--radius-pill);
  background:var(--warn);color:#1a1300;font:600 11.5px/1 var(--font-text);
  box-shadow:var(--shadow-md);pointer-events:none}

/* THE INSTANT PREVIEW: two players on top of each other, the one on screen
   opaque. Opacity, not display or visibility, so the cued one keeps decoding
   its first frame and the cut is a swap rather than a load. A vertical reel
   crops the game the way the render does unless it was asked to fit it. */
.studio-pv{position:absolute;inset:0;background:#000;container-type:size}
.studio-pv-v{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;opacity:0}
.studio-pv-v.is-on{opacity:1}
/* The lyrics over the clips; the overlay is the reel's own shape. */
.studio-pv-lyr{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
  background:transparent !important;pointer-events:none}
.studio-player.is-vertical .studio-pv-v{object-fit:cover}
.studio-player.is-vertical.is-fit .studio-pv-v{object-fit:contain;background:transparent}
/* The render's boxblur=24:2 and eq=brightness=-0.12:saturation=0.8, near
   enough: scaled past the edges so the blur has no lighter rim. */
.studio-pv-bg{display:none;position:absolute;inset:0;width:100%;height:100%;
  filter:blur(14px) brightness(.84) saturate(.8);transform:scale(1.12)}
.studio-player.is-vertical.is-fit .studio-pv-bg{display:block}
/* Near fit: the middle three quarters of the game in a 4:3 band across the middle, as the render
   crops it (studio.NEAR_KEEP). */
.studio-player.is-vertical.is-near .studio-pv-v{object-fit:cover;inset:auto 0;top:50%;height:auto;
  aspect-ratio:4/3;transform:translateY(-50%)}
/* A frame set by hand (studio.frame_settings): the band is the width's kept share at the frame's
   width, no taller than the frame, placed where it was put; the crop taken from where it was put. */
.studio-player.is-vertical.is-custom .studio-pv-v{object-fit:cover;inset:auto 0;width:100%;transform:none;
  height:min(100cqh,calc(100cqw * 9 / (16 * var(--kp,0.75))));
  top:calc((100cqh - min(100cqh,calc(100cqw * 9 / (16 * var(--kp,0.75))))) * var(--fy,0.5));
  object-position:calc(var(--fx,0.5) * 100%) 50%}
.studio-player.is-vertical.is-plainbg .studio-pv-bg{display:none}
.studio-player.is-vertical.is-plainbg .studio-pv{background:var(--pvbg,#000)}
.studio-pv-tag{position:absolute;top:var(--space-5);left:var(--space-5);z-index:1;
  max-width:calc(100% - 2 * var(--space-5));
  padding:var(--space-3) var(--space-5);border-radius:var(--radius-sm);
  background:var(--on-media-scrim);color:var(--on-media);font:600 11.5px/1.3 var(--font-text);
  pointer-events:none}
/* Its bar, where the browser puts its own on the rendered video: along the
   foot of the picture, on screen while paused or pointed at, out of the way
   while it plays. Above the handle frame, which covers the whole picture. */
.studio-pv-bar{position:absolute;left:0;right:0;bottom:0;z-index:2;
  display:flex;align-items:center;gap:var(--space-3);
  padding:var(--space-6) var(--space-4) var(--space-3);
  background:linear-gradient(to top,rgba(0,0,0,.72),rgba(0,0,0,0));color:var(--on-media);
  opacity:0;transition:opacity .18s ease}
/* :focus-visible, not :focus-within: a button pressed with the mouse keeps
   focus, and would pin the bar over the picture for the rest of the reel. */
.studio-pv:not(.is-playing) .studio-pv-bar,.studio-pv:hover .studio-pv-bar,
.studio-pv-bar:has(:focus-visible){opacity:1}
.studio-pv-btn{flex:none;min-width:30px;height:30px;padding:0 var(--space-2);border:0;border-radius:var(--radius-sm);
  background:transparent;color:var(--on-media);font-size:15px;line-height:1;cursor:pointer}
.studio-pv-btn:hover{background:rgba(255,255,255,.16)}
.studio-pv-btn:focus-visible{outline:var(--focus-ring-width) solid var(--on-media);outline-offset:1px}
.studio-pv-time{flex:none;font-size:12px;color:var(--on-media)}
/* White, like the bar it stands in for: the accent budget has no room for it. */
.studio-pv-seek{flex:1 1 auto;min-width:2rem;accent-color:var(--on-media);cursor:pointer}
.studio-player:fullscreen{border-radius:0}
/* A 9:16 player is narrow: the clock goes before mute and fullscreen do. */
@container (max-width:300px){.studio-pv-time{display:none}.studio-pv-bar{gap:var(--space-1)}}
.studio-auto{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3) var(--space-4);
  padding-top:var(--space-3);border-top:var(--border-hair) solid var(--border-subtle)}
.studio-auto-state{font-size:12px;color:var(--text-secondary)}
.studio-auto-state:empty{display:none}

.studio-acts{gap:var(--space-4);flex-wrap:wrap}

/* THE EXPLANATIONS, FOLDED. Everything here used to be amber bullets in one
   stack; only the first block is ever a problem, and the rest is the planner
   accounting for itself, which is worth keeping and not worth shouting. */
.studio-why{display:flex;flex-direction:column;gap:var(--space-4);font-size:12.5px}
.studio-alert{padding:var(--space-4) var(--space-5);border-radius:var(--radius-sm);
  background:var(--warn-muted);border:var(--border-hair) solid var(--warn);
  border-width:0 0 0 3px}
.studio-alert-h{margin:0 0 var(--space-3);font-weight:600;color:var(--text-primary)}
.studio-alert ul{margin:0;padding-left:18px;color:var(--text-secondary);list-style:disc}
.studio-alert li{margin-bottom:2px;line-height:1.5}
.studio-alert li::marker{color:var(--warn)}
.studio-fold{border-top:var(--border-hair) solid var(--border-subtle);padding-top:var(--space-4)}
.studio-fold summary{display:flex;align-items:center;gap:var(--space-4);cursor:pointer;
  color:var(--text-secondary);list-style:none}
.studio-fold summary::-webkit-details-marker{display:none}
/* The chevron the flex summary drops. Right when shut, down when open. */
.studio-fold summary::before{content:"";flex:none;width:5px;height:5px;margin:0 1px 2px 2px;
  border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;
  transform:rotate(-45deg);transition:transform var(--dur-fast) var(--ease-standard)}
.studio-fold[open] summary::before{transform:rotate(45deg);margin-bottom:4px}
.studio-fold summary:hover{color:var(--text-primary)}
.studio-fold summary:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px;border-radius:var(--radius-xs)}
.studio-fold-n{margin-left:auto;padding:1px 7px;border-radius:var(--radius-pill);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);
  font:11px var(--font-mono);color:var(--text-tertiary)}
.studio-fold-lede{margin:var(--space-4) 0 var(--space-2);color:var(--text-secondary)}
/* The reset takes the markers off every ul; these want them back, so that a
   note running to three lines still reads as one note. */
.studio-fold-list{margin:var(--space-4) 0 0;padding-left:26px;color:var(--text-secondary);list-style:disc}
.studio-fold-list li{line-height:1.5;margin-bottom:var(--space-4)}
.studio-fold-list li:last-child{margin-bottom:0}
.studio-fold-list li::marker{color:var(--text-tertiary)}
.studio-fold-flat{margin:0;padding-top:var(--space-4);
  border-top:var(--border-hair) solid var(--border-subtle);color:var(--text-secondary)}
.studio-add-btn{align-self:flex-start}
.studio-tl-bar{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3)}
.studio-clock{min-width:70px;color:var(--text-primary)}
.studio-check{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--text-secondary)}
.studio-spacer{flex:1}
.studio-hint{font-size:12px}
.studio-edit{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:var(--space-5);align-items:start}
@media (max-width:1100px){.studio-edit{grid-template-columns:1fr}}
.studio-tl{display:flex;background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);overflow:hidden;min-width:0}
.studio-tl:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.studio-labels{flex:none;width:88px;border-right:var(--border-hair) solid var(--border-subtle);background:var(--surface)}
.st-lab{display:flex;align-items:center;padding:0 10px;font-size:11px;color:var(--text-tertiary);
  text-transform:uppercase;letter-spacing:.05em;border-bottom:var(--border-hair) solid var(--border-subtle)}
.st-lab:nth-child(1){height:26px}.st-lab:nth-child(2){height:64px}.st-lab:nth-child(3){height:30px}
.st-lab:nth-child(4){height:34px}.st-lab:nth-child(5){height:38px}.st-lab:nth-child(6){height:30px}
/* The heights here are only what the labels are before the first draw: the
   timeline sets each one from STUDIO_ROW, which is where they are decided. */
.st-lab:nth-child(7){height:106px;border-bottom:0}
.studio-scroll{flex:1;overflow-x:auto;overflow-y:hidden;min-width:0}
.st-area{position:relative;margin-right:24px;user-select:none;touch-action:pan-x}
.st-ruler{position:absolute;left:0;right:0;cursor:pointer;border-bottom:var(--border-hair) solid var(--border-subtle)}
.st-tick{position:absolute;top:6px;transform:translateX(2px);font:11px var(--font-mono);color:var(--text-tertiary);white-space:nowrap}
.st-beat{position:absolute;width:1px;background:var(--border-subtle);opacity:.55;pointer-events:none}
.st-beat.is-bar{background:var(--border-strong);opacity:.8}
.st-shot{position:absolute;box-sizing:border-box;border:2px solid rgba(0,0,0,.35);border-radius:6px;
  background-size:cover;background-position:center;background-color:#222;cursor:grab;overflow:hidden}
.st-shot:active{cursor:grabbing}
.st-shot.is-hero{border-color:var(--warn)}
.st-shot.is-sel{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}
/* One of several shots picked together (shift- or ctrl-click). */
.st-shot.is-multi{border-color:var(--accent);box-shadow:inset 0 0 0 999px color-mix(in srgb, var(--accent) 18%, transparent)}
/* Shots locked together: a band under the run, a padlock on its first shot. */
.st-lockband{position:absolute;height:6px;border-radius:3px;background:var(--warn);opacity:.85;pointer-events:none;z-index:3}
.st-lockband-ico{position:absolute;left:2px;top:-15px;width:14px;height:14px;border-radius:3px;
  background:var(--warn);display:flex;align-items:center;justify-content:center}
.st-lockband-ico svg{width:10px;height:10px;fill:none;stroke:#111;stroke-width:2.4}
/* Edited since the last render. A corner flag rather than a border, because
   the borders here are already spoken for by the selection and the hero shot,
   and this has to be readable on top of either. */
.st-shot.is-edited::after{content:"";position:absolute;top:0;right:0;width:0;height:0;
  border-top:12px solid var(--warn);border-left:12px solid transparent;pointer-events:none}
.st-shot-name{position:absolute;left:4px;top:3px;right:12px;padding:1px 5px;border-radius:3px;
  font:600 11px/1.3 var(--font-text);color:var(--on-media);background:var(--on-media-scrim);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;max-width:max-content}
.st-kill{position:absolute;bottom:6px;width:12px;height:12px;margin-left:-6px;transform:rotate(45deg);
  background:#fff;border:2px solid var(--accent);cursor:ew-resize}
/* EVERY OTHER KILL THE SHOT SHOWS. Hollow, so the shot's own kill -- the one
   the cut is built around -- still reads as the one in charge; and smaller,
   because a row of equal diamonds says nothing about which is which. */
.st-kill.is-extra{width:9px;height:9px;margin-left:-4.5px;bottom:8px;
  background:transparent;border-color:var(--text-secondary)}
.st-kill.is-extra.is-pinned{background:var(--accent);border-color:var(--accent)}
/* The cut BEFORE a shot, as a handle of its own: there was only the one after,
   so a lead-up could not be shortened from the side it is on. */
.st-trim-l{position:absolute;top:0;left:0;width:10px;height:100%;cursor:ew-resize;
  background:linear-gradient(270deg,transparent,rgba(255,255,255,.35));z-index:1}
.st-trim{position:absolute;top:0;right:0;width:10px;height:100%;cursor:ew-resize;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35))}
.st-tr{position:absolute;height:22px;margin-left:0;transform:translateX(-50%);padding:0 5px;min-width:18px;
  border-radius:4px;border:var(--border-hair) solid var(--border-strong);background:var(--surface);
  color:var(--text-primary);font:600 10px/1 var(--font-mono);cursor:pointer}
.st-tr.is-cut{background:transparent;border-color:transparent;color:var(--text-tertiary)}
.st-tr.is-sel{border-color:var(--accent);color:var(--accent)}
.st-fx{position:absolute;transform:translateX(-50%);height:22px;padding:0 6px;border-radius:11px;cursor:pointer;
  background:var(--accent);color:var(--text-on-accent);border:0;font:600 10px/1 var(--font-mono);white-space:nowrap}
.st-fx.is-hero{background:var(--warn);color:#1a1300}
.st-speed{position:absolute;left:0;overflow:visible;pointer-events:none}
.st-speed-base{stroke:var(--border-subtle);stroke-width:1;stroke-dasharray:3 4}
.st-speed-line{fill:none;stroke:var(--text-tertiary);stroke-width:2;vector-effect:non-scaling-stroke}
.st-speed-line.is-ramp{stroke:var(--ok)}
.st-text{position:absolute;height:20px;padding:0 6px;border-radius:4px;border:var(--border-hair) solid var(--border-strong);
  background:var(--surface);color:var(--text-secondary);font-size:11px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;text-align:left;cursor:pointer}
.st-music{position:absolute;left:0;display:block}
.st-ph{position:absolute;top:0;width:2px;margin-left:-1px;background:var(--danger);pointer-events:none}
.studio-insp{position:sticky;top:var(--space-4)}
.studio-insp-tabs{margin:var(--space-4) var(--space-4) 0}
.studio-insp-body{display:flex;flex-direction:column;gap:var(--space-4);max-height:70vh;overflow:auto}
.studio-insp-head{display:flex;justify-content:space-between;align-items:center;gap:var(--space-3)}
.studio-field{display:flex;flex-direction:column;gap:6px}
.studio-nudge{gap:4px}
/* The inspector's choices: one line per pick, a chip per effect that is on.
   Making a choice is the picker's job (.studio-fxp-*), where every option plays. */
/* The saved VALORANT match records, under the match-record line on Clips. */
.clip-matchlist{display:flex;flex-direction:column;gap:var(--space-2);margin-top:var(--space-3)}
.clip-mhead{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);flex-wrap:wrap;
  font-size:12.5px;color:var(--text-secondary)}
.clip-mlist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:var(--space-1);
  max-height:320px;overflow:auto}
.clip-mrow{display:grid;grid-template-columns:minmax(150px,1.4fr) minmax(130px,1fr) auto auto minmax(0,auto);
  align-items:center;gap:var(--space-3);padding:var(--space-2) var(--space-3);border-radius:var(--radius-sm);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);font-size:13px}
.clip-mrow.is-here{border-color:var(--accent)}
.clip-mmap{display:flex;flex-direction:column;min-width:0}
.clip-mmap b{color:var(--text-primary);font-weight:600}
.clip-mmap .muted,.clip-mwhen{font-size:12px}
.clip-mres{font-weight:600;white-space:nowrap}
.clip-mres.is-won{color:var(--ok)}
.clip-mres.is-lost{color:var(--danger)}
.clip-mkda{white-space:nowrap;color:var(--text-primary)}
.clip-mhere{display:inline-flex;align-items:center;gap:var(--space-2);font-size:12px;color:var(--accent-text);white-space:nowrap;cursor:pointer}
.clip-mrow.is-off{opacity:.55;border-color:var(--border-subtle)}
@media (max-width:719px){.clip-mrow{grid-template-columns:1fr auto}}

.studio-pick-btn{display:flex;align-items:center;gap:var(--space-2);width:100%;min-height:36px;
  padding:var(--space-2) var(--space-3);border-radius:var(--radius-sm);cursor:pointer;font:inherit;text-align:left;
  background:var(--surface-sunken);color:var(--text-primary);border:var(--border-hair) solid var(--border-subtle)}
.studio-pick-btn:hover{border-color:var(--border-strong)}
.studio-pick-btn:focus-visible,.studio-pick-x:focus-visible,.studio-fxp-card:focus-visible{
  outline:2px solid var(--accent);outline-offset:2px}
.studio-pick-name{flex:1;min-width:0;font-size:13px}
.studio-pick-go{font-size:12px;color:var(--accent-text);flex:none}
.studio-pick-multi{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2)}
.studio-pick-chip{display:inline-flex;align-items:center;gap:var(--space-1);max-width:100%;
  padding:var(--space-1) var(--space-1) var(--space-1) var(--space-2);border-radius:var(--radius-sm);font-size:12.5px;
  color:var(--text-primary);background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle)}
.studio-pick-x{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;padding:0;
  border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text-tertiary);cursor:pointer;font:inherit}
.studio-pick-x:hover{color:var(--text-primary);background:var(--surface)}

/* The picker. Its point is that you watch the options, so the one being
   looked at is the biggest thing in it: a narrow list of playing rows down
   the left, and the stage -- the example at the largest 16:9 the dialog
   holds, centred -- taking everything else. */
.studio-fxp-modal{width:min(1480px,100%);height:min(92vh,1000px);max-height:none;gap:var(--space-4)}
.studio-fxp-head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:var(--space-4)}
.studio-fxp-head .modal-title{margin:0}
.studio-fxp-q{width:min(360px,100%)}
.studio-fxp-main{display:grid;grid-template-columns:minmax(240px,300px) minmax(0,1fr);gap:var(--space-6);
  min-height:0;flex:1}
.studio-fxp-list{overflow:auto;min-height:0;padding-right:var(--space-2)}
.studio-fxp-grid.bin-grid{display:flex;flex-direction:column;gap:var(--space-2)}
.studio-fxp-sec{margin:var(--space-2) 0 var(--space-3);font-size:12px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--text-tertiary)}
.studio-fxp-sec:first-child{margin-top:0}
/* A row: a small playing thumbnail, the name, one line of what it does. */
.studio-fxp-card.bin-card{position:relative;flex-direction:row;align-items:center;min-height:0}
.studio-fxp-card .bin-shot{flex:none;width:112px}
.studio-fxp-card .bin-shot .bin-tag{left:3px;top:3px;padding:1px 4px;font-size:9.5px}
.studio-fxp-card .bin-shot .bin-sample{display:none}
.studio-fxp-card .bin-shot .bin-none{font-size:9.5px}
.studio-fxp-card .bin-meat{padding:6px 10px;min-width:0;gap:2px}
.studio-fxp-card .bin-name{font-size:13px}
.studio-fxp-card .bin-blurb{display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;
  font-size:11.5px}
.studio-fxp-tick{position:absolute;right:var(--space-2);top:50%;transform:translateY(-50%);display:flex;
  align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;font-size:12px;
  font-weight:700;background:var(--accent);color:var(--text-on-accent)}
.studio-fxp-card.is-on .bin-meat{padding-right:36px}
.studio-fxp-none{margin:var(--space-4) 0}
/* The stage: the example as large as the space allows, never cropped. */
.studio-fxp-prev{display:flex;flex-direction:column;gap:var(--space-4);min-height:0;min-width:0}
.studio-fxp-prev.is-empty{visibility:hidden}
.studio-fxp-prevshot{flex:1 1 auto;min-height:0;display:flex;align-items:center;justify-content:center;
  container-type:size;background:#000;border-radius:var(--radius-md);overflow:hidden}
.studio-fxp-prevshot .bin-shot{width:min(100cqw,calc(100cqh * 16 / 9));height:auto;aspect-ratio:16/9;
  border-radius:var(--radius-sm)}
.studio-fxp-prevshot .bin-shot video,.studio-fxp-prevshot .bin-shot img{object-fit:contain;background:#000}
.studio-fxp-prevshot .bin-shot .bin-tag{left:10px;top:10px;font-size:12px;padding:3px 8px}
.studio-fxp-prevshot .bin-shot .bin-sample{right:10px;bottom:10px;font-size:11px}
.studio-fxp-prevfoot{flex:none;display:flex;align-items:flex-start;gap:var(--space-5)}
.studio-fxp-prevtext{flex:1;min-width:0;display:flex;flex-direction:column;gap:var(--space-1)}
.studio-fxp-prevname{margin:0;display:flex;align-items:baseline;gap:var(--space-2);color:var(--text-primary);
  font-size:16px}
.studio-fxp-prevnote:empty{display:none}
.studio-fxp-count{margin-right:auto}
/* Narrow: the stage on top, the list under it. */
@media (max-width:759px){
  .studio-fxp-modal{height:min(94vh,1000px)}
  .studio-fxp-main{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(180px,42%) minmax(0,1fr)}
  .studio-fxp-prev{order:-1}
}
/* ---- the command list (Ctrl+K) and the key sheet (?) ---------------------
   Both are drawn from ui/commands.py. The list is a single column because the
   eye runs down it while typing; the sheet is columns because it is read, not
   searched. A row that cannot run keeps its full contrast and says why
   underneath -- dimming it to 40% is the same silence as greying out. */
.studio-palbtn{margin-left:auto;gap:var(--space-3)}
.studio-palbtn kbd{font-size:10.5px}
.studio-pal{width:min(680px,100%);max-height:min(76vh,680px);gap:0;padding:0;overflow:hidden}
.studio-pal-head{display:flex;align-items:center;gap:var(--space-4);padding:var(--space-5) var(--space-6);
  border-bottom:var(--border-hair) solid var(--border-subtle)}
.studio-pal-ico{color:var(--text-tertiary);font-size:15px}
.studio-pal-q{flex:1;min-width:0;height:34px;border:0;background:transparent;padding:0;font-size:16px}
.studio-pal-q:focus{outline:none;box-shadow:none}
.studio-pal-count{flex:none;font-size:11.5px;white-space:nowrap}
.studio-pal-list{flex:1;min-height:0;overflow:auto;padding:var(--space-3) 0}
.studio-pal-grp{margin:var(--space-4) var(--space-6) var(--space-2);font-family:var(--font-micro);
  font-size:10.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-tertiary)}
.studio-pal-grp:first-child{margin-top:0}
.studio-pal-row{display:flex;align-items:center;gap:var(--space-5);width:100%;
  padding:var(--space-4) var(--space-6);border:0;border-left:2px solid transparent;background:transparent;
  color:var(--text-primary);font:inherit;font-size:13.5px;text-align:left;cursor:pointer}
.studio-pal-row:hover{background:var(--surface-hover)}
/* ACCENT BUDGET: the "on" row of a list, same as a segmented cell. */
.studio-pal-row.is-on{background:var(--accent-muted);border-left-color:var(--accent)}
.studio-pal-lab{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.studio-pal-why{font-size:11.5px;color:var(--warn)}
.studio-pal-keys{flex:none;display:flex;gap:var(--space-1)}
.studio-pal-row.is-off .studio-pal-keys{opacity:.6}
.studio-pal-none{margin:var(--space-6);color:var(--text-secondary);font-size:13px}
.studio-pal-foot{display:flex;align-items:center;gap:var(--space-5);padding:var(--space-4) var(--space-6);
  border-top:var(--border-hair) solid var(--border-subtle);background:var(--surface-sunken);
  font-size:11.5px;color:var(--text-tertiary)}
.studio-keys{width:min(1120px,100%);max-height:min(88vh,900px)}
.studio-keys-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-5)}
.studio-keys-head .modal-title{margin:0 0 var(--space-2)}
.studio-keys-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:var(--space-6);
  overflow:auto;min-height:0}
.studio-keys-grp h3{margin:0 0 var(--space-1);font-size:13px}
.studio-keys-grp>.studio-small{margin:0 0 var(--space-3)}
.studio-keys-row{display:flex;align-items:center;gap:var(--space-2);margin:0;padding:var(--space-3) 0;
  border-bottom:var(--border-hair) solid var(--border-subtle);font-size:12.5px}
.studio-keys-row span:first-child{flex:1;min-width:0}
.studio-keys-or{flex:none;font-size:10.5px;color:var(--text-tertiary)}
@media (max-width:759px){
  .studio-palbtn{order:3;margin-left:0}
  .studio-pal-head,.studio-pal-row,.studio-pal-foot{padding-inline:var(--space-5)}
}
.studio-tip{margin:0;padding:8px 10px;border-radius:var(--radius-sm);background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);font-size:12.5px;color:var(--text-secondary)}
.studio-small{font-size:12px;margin:0}
.st-tr.is-compact{width:10px;min-width:10px;height:10px;padding:0;margin-top:6px;border-radius:2px;transform:translateX(-50%) rotate(45deg);
  background:var(--accent);border-color:var(--accent)}
.st-tr.is-compact.is-cut{background:transparent;border-color:var(--border-strong)}
.st-fx.is-compact{min-width:14px;height:14px;padding:0 4px;margin-top:4px;font-size:9px;border-radius:7px}
.studio-sg-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--space-4)}
.studio-sg-title{display:flex;flex-direction:column;gap:2px;min-width:0}
.studio-sg-name{font-size:16px;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.studio-sg-body{display:flex;flex-direction:column;gap:var(--space-3);margin-top:var(--space-4)}
.studio-sg-wave{width:100%;display:block;border-radius:var(--radius-sm);background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle);cursor:grab;touch-action:none}
.studio-sg-detail{cursor:crosshair}
.studio-mk-part{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-mk-body{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-adding{font-size:12.5px;color:var(--accent)}
.studio-del-btn{color:var(--danger)}
.studio-mk-transport{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3)}
.studio-mk-play{min-width:72px}
/* A BUTTON THAT RENAMES ITSELF MUST NOT RESIZE ITSELF. Play/Pause swaps the
   label under a pointer that has not moved; without a floor on the width the
   button changes size on every press, the row reflows around it, and the next
   click lands on whatever slid into the gap. */
.studio-transport{min-width:76px}
.studio-transport-wide{min-width:124px}

/* THE INTRO CLIP. A band over the head of the video row, because that is
   literally what it is: the reel is untouched underneath it. Hatched so it
   never reads as a shot, and translucent so the shot it covers still shows. */
.st-introclip{position:absolute;box-sizing:border-box;border-radius:6px;cursor:pointer;
  border:2px dashed var(--accent-text);
  background:repeating-linear-gradient(135deg,rgba(0,0,0,.55) 0 8px,rgba(0,0,0,.28) 8px 16px)}
.st-introclip:hover{background:repeating-linear-gradient(135deg,rgba(0,0,0,.62) 0 8px,rgba(0,0,0,.34) 8px 16px)}
.st-introclip-tag{position:absolute;left:5px;bottom:4px;padding:1px 6px;border-radius:3px;
  font:600 10px/1.4 var(--font-text);color:var(--on-media);background:var(--on-media-scrim);white-space:nowrap}

/* The inspector's one line about the intro; the editing is in the dialog. */
.studio-introrow{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3);
  justify-content:space-between;padding:var(--space-4);border-radius:var(--radius-sm);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);font-size:12.5px}
.studio-introrow-on{display:flex;flex-direction:column;min-width:0;gap:1px}
.studio-introrow-on b{color:var(--text-primary)}

.studio-intro-modal{width:min(760px,100%)}
.studio-intro-body{display:flex;flex-direction:column;gap:var(--space-5);max-width:none}
.studio-intro-lede{margin:0}
/* The library. One card per intro, the whole card picks it, Delete sits apart
   so a click that means "use this" can never mean "destroy this". */
.studio-intro-lib{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:var(--space-4)}
.studio-introcard{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) var(--space-4);
  border-radius:var(--radius-sm);background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle)}
.studio-introcard:hover{border-color:var(--border-strong)}
.studio-introcard.is-on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.studio-introcard-hit{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;text-align:left;
  padding:0;background:none;border:0;color:inherit;font:inherit;cursor:pointer}
.studio-introcard-name{font-weight:600;color:var(--text-primary);font-size:12.5px}
.studio-introcard-meta{font-size:11px}
.studio-intro-player{background:#000;border-radius:var(--radius-md);overflow:hidden;
  display:flex;align-items:center;justify-content:center;max-height:38vh}
.studio-intro-player video{width:100%;max-height:38vh;object-fit:contain;background:#000;display:block}
.studio-intro-edit{display:flex;flex-direction:column;gap:var(--space-4)}
.studio-intro-trim{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-intro-trim input[type=range]{flex:1 1 160px;min-width:0;accent-color:var(--accent)}
.studio-intro-opts{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:var(--space-5)}
.studio-mk-seek{flex:1 1 180px;min-width:0;accent-color:var(--accent)}
.studio-mk-clock{min-width:108px;font-size:12.5px;color:var(--text-primary)}
.studio-yt{width:min(560px,100%)}
.studio-yt-body{display:flex;flex-direction:column;gap:var(--space-3);max-width:none}
.studio-yt-hint{font-size:12.5px;margin:0}
.studio-yt-progress{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-yt-status{margin:0;font-size:13px;color:var(--text-secondary);overflow-wrap:anywhere}
.studio-yt-error{margin:0;font-size:13px;color:var(--danger);overflow-wrap:anywhere}
/* No percentage yet (reading the link, converting, finding the beat): a band that moves. */
.meter-fill.is-busy{background:linear-gradient(90deg,transparent 0%,var(--accent) 40%,var(--accent) 60%,transparent 100%);
  background-size:40% 100%;background-repeat:no-repeat;animation:studio-yt-busy 1.2s linear infinite}
@keyframes studio-yt-busy{from{background-position:-40% 0}to{background-position:140% 0}}
@media (prefers-reduced-motion:reduce){.meter-fill.is-busy{animation:none;background:var(--accent);opacity:.6}}
"""

CSS = CSS + STUDIO_CSS

# The Studio's editor: the timeline tab laid out as one screen. Its own block,
# after the Studio's, so it wins where the two describe the same element.
EDITOR_CSS = r"""
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}
#view-studio.is-editing{max-width:none;padding-top:var(--space-5);padding-bottom:var(--space-5)}
#view-studio.is-editing .studio{padding-bottom:0;gap:var(--space-4)}
.studio-editor{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:var(--space-5);
  height:var(--ed-h,calc(100vh - 170px));min-height:600px}
.studio-editor.hide{display:none}
.ed-main{display:flex;flex-direction:column;gap:var(--space-3);min-width:0;min-height:0}
.ed-toolbar{display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap}
.ed-name{flex:0 1 320px;min-width:180px;font-weight:600}
.ed-facts{margin:0;font-size:12.5px}
.ed-stage{flex:1 1 auto;min-height:200px;display:flex;align-items:center;justify-content:center;
  background:#000;border-radius:var(--radius-md);overflow:hidden;position:relative}
.ed-stage .studio-player{height:100%;max-width:100%;aspect-ratio:16/9;border-radius:0}
.ed-stage .studio-player.is-vertical{aspect-ratio:9/16}
.ed-stage .studio-player video{width:100%;height:100%}
.ed-transport{flex:none}
.ed-main .studio-tl{flex:none;max-height:340px}
.ed-side{display:flex;flex-direction:column;gap:var(--space-4);min-height:0;overflow:hidden}
.ed-side .studio-sync{flex:none;padding:var(--space-4)}
.ed-side .studio-pending{max-height:96px;overflow:auto}
.ed-side .studio-insp{position:static;flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.ed-side .studio-insp-body{flex:1 1 auto;max-height:none;min-height:0;overflow:auto;overscroll-behavior:contain}
.ed-side .studio-why{flex:none;max-height:28%;overflow:auto}
.ed-side .studio-why:empty{display:none}
@media (max-width:1100px){
  .studio-editor{grid-template-columns:1fr;height:auto}
  .ed-stage{min-height:300px}
  .ed-side{overflow:visible}
  .ed-side .studio-insp-body{max-height:70vh}
}

/* The effect preview: the example of whatever part the pointer is on. */
.ed-fx{flex:none;display:grid;grid-template-columns:168px minmax(0,1fr);gap:var(--space-4);align-items:center;
  padding:var(--space-3);border-radius:var(--radius-md);background:var(--surface-sunken);
  border:var(--border-hair) solid var(--border-subtle)}
.ed-fx.hide{display:none}
.ed-fx-shot{aspect-ratio:16/9;background:#000;border-radius:var(--radius-sm);overflow:hidden;position:relative}
.ed-fx-shot video,.ed-fx-shot img{width:100%;height:100%;object-fit:cover;display:block}
.ed-fx-shot .bin-none{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font:500 10px var(--font-mono);color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.08em}
.ed-fx-text{display:flex;flex-direction:column;gap:4px;font-size:12.5px;min-width:0}
.ed-fx-text strong{color:var(--text-primary);font-size:13.5px}

/* Inspector groups: folded sections so a long list of options is a short
   list of headings, and the one being worked on stays open. */
.ed-group{border-top:var(--border-hair) solid var(--border-subtle);padding-top:var(--space-3)}
/* THE INSPECTOR'S BLOCKS: Footage / Cut in / On the kill / Camera on a shot,
   Music / Words / Look / Start & end / You on the reel. Each is a card of its
   own with a header that says what is set, so one kind of setting visibly ends
   where the next begins. */
.ed-block{border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md);
  background:var(--surface-sunken);padding:0 var(--space-3) var(--space-2);scroll-margin-top:var(--space-3)}
.ed-block + .ed-block{margin-top:var(--space-2)}
.ed-block-head{display:flex;align-items:center;gap:var(--space-2);padding:var(--space-3) 0 var(--space-2);
  border-bottom:var(--border-hair) solid var(--border-subtle);margin-bottom:var(--space-2)}
.ed-block-ico{width:18px;height:18px;flex:0 0 auto;fill:none;stroke:var(--accent);stroke-width:1.8;
  stroke-linecap:round;stroke-linejoin:round}
.ed-block-name{font:700 14px/1.2 var(--font-text);color:var(--text-primary);flex:0 0 auto}
.ed-block-sum{margin-left:auto;font-size:12px;color:var(--text-tertiary);min-width:0;text-align:right}
.ed-block-body{display:flex;flex-direction:column;gap:var(--space-3)}
.ed-block-body > .ed-group:first-child{border-top:0;padding-top:0}
.ed-group.is-solo{border-top:0;padding-top:0}
.ed-group.is-solo > summary{display:none}
.ed-group.is-solo > .ed-group-body{padding-top:0}
.ed-blocknav{display:flex;flex-wrap:wrap;gap:6px}
.ed-blocknav-b{border:var(--border-hair) solid var(--border-subtle);background:var(--surface);color:var(--text-secondary);
  border-radius:999px;padding:3px 10px;font-size:12px;cursor:pointer}
.ed-blocknav-b:hover,.ed-blocknav-b:focus-visible{color:var(--text-primary);border-color:var(--accent)}

/* THE SHOT'S FOOTAGE: the part in the reel playing, over the whole clip with
   a box on that part and a tick on each kill. */
.studio-strip{display:flex;flex-direction:column;gap:var(--space-2)}
.studio-strip-view{position:relative;border-radius:var(--radius-sm);overflow:hidden;background:#000;aspect-ratio:16/9}
.studio-strip-video{display:block;width:100%;height:100%;object-fit:contain}
.studio-strip-cap{position:absolute;left:6px;bottom:6px;padding:1px 6px;border-radius:4px;font-size:11px;
  background:var(--on-media-scrim);color:var(--on-media)}
.studio-strip-track{position:relative;display:flex;height:42px;border-radius:var(--radius-sm);overflow:hidden;
  background:var(--surface);touch-action:none;user-select:none}
.studio-strip-th{flex:1 1 0;background-size:cover;background-position:center;opacity:.9}
.studio-strip-dim{position:absolute;top:0;bottom:0;background:rgba(0,0,0,.62);pointer-events:none}
.studio-strip-dim.is-l{left:0}
.studio-strip-dim.is-r{right:0}
.studio-strip-box{position:absolute;top:0;bottom:0;box-sizing:border-box;border:2px solid var(--accent);min-width:14px;
  border-radius:4px;cursor:grab;z-index:2}
.studio-strip-box:active{cursor:grabbing}
.studio-strip-nudge{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px}
.studio-strip-track{cursor:pointer}
.studio-strip-h{position:absolute;top:-2px;bottom:-2px;width:10px;background:var(--accent);cursor:ew-resize}
.studio-strip-h.is-head{left:-6px;border-radius:4px 0 0 4px}
.studio-strip-h.is-tail{right:-6px;border-radius:0 4px 4px 0}
.studio-strip-kill{position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;background:rgba(255,255,255,.55);
  pointer-events:none;z-index:3}
.studio-strip-kill.is-main{background:var(--warn);width:3px}
.ed-group > summary{display:flex;align-items:center;gap:var(--space-3);cursor:pointer;list-style:none;
  font:600 12px/1.3 var(--font-text);letter-spacing:.06em;text-transform:uppercase;color:var(--text-secondary);
  padding:4px 0}
.ed-group > summary::-webkit-details-marker{display:none}
.ed-group > summary::after{content:"";margin-left:auto;width:6px;height:6px;border-right:1.5px solid currentColor;
  border-bottom:1.5px solid currentColor;transform:rotate(45deg);transition:transform var(--dur-fast) var(--ease-standard)}
.ed-group:not([open]) > summary::after{transform:rotate(-45deg)}
.ed-group > summary:hover{color:var(--text-primary)}
.ed-group-body{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-3) 0 var(--space-2)}
.ed-group-note{font-weight:400;text-transform:none;letter-spacing:0;color:var(--text-tertiary);font-size:11.5px}

/* Nine places for the handle, laid out as the frame they stand for. */
.ed-grid9{display:grid;grid-template-columns:repeat(3,28px);gap:4px}
.ed-grid9 button{height:22px;border-radius:4px;border:var(--border-hair) solid var(--border-subtle);
  background:var(--surface-sunken);cursor:pointer;padding:0}
.ed-grid9 button.is-on{background:var(--accent);border-color:var(--accent)}
.ed-row{display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap}

/* The frame over the player: where the handle and the camera will be. */
.ed-frame{position:absolute;inset:0;pointer-events:none}
.ed-frame.hide{display:none}
.ed-handle{position:absolute;pointer-events:auto;cursor:grab;padding:2px 8px;border-radius:4px;
  font:600 13px/1.4 var(--font-text);color:var(--on-media);background:var(--on-media-scrim);
  outline:1px dashed rgba(255,255,255,.8);white-space:nowrap;user-select:none;touch-action:none}
.ed-handle:active{cursor:grabbing}
.ed-handle.hide{display:none}
/* The lyrics stand-in: the reel's own red, so it reads as the words and not the handle. */
.ed-lyrics{font-family:var(--font-display);letter-spacing:.04em;color:#fff;background:rgba(224,38,58,.55)}
.ed-cambox{position:absolute;border:2px dashed var(--warn);background:rgba(255,200,60,.12);pointer-events:none}
.ed-cambox span{position:absolute;left:4px;top:2px;font:600 11px var(--font-text);color:var(--warn)}
/* ---- the boxes the lyrics are dealt into (U28) ---------------------------
   Drawn ON the picture, so every colour here is the on-media pair rather than
   a theme token: a frame of gameplay is not a surface this app controls, and
   a border in --accent is invisible over a blue sky. The number sits in a
   scrim for the same reason. */
.ed-boxes{position:absolute;touch-action:none;cursor:crosshair;z-index:3}
.ed-box{position:absolute;box-sizing:border-box;border:2px dashed rgba(255,255,255,.85);
  background:rgba(0,0,0,.18);cursor:move}
.ed-box.is-on{border-style:solid;border-color:var(--accent);background:rgba(77,159,255,.16)}
.ed-box-num{position:absolute;left:-1px;top:-1px;min-width:18px;height:18px;display:flex;
  align-items:center;justify-content:center;padding:0 4px;font:700 11px var(--font-mono);
  color:var(--on-media);background:var(--on-media-scrim);pointer-events:none}
.ed-box.is-on .ed-box-num{background:var(--accent);color:var(--text-on-accent)}
.ed-box-h{position:absolute;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:2px;
  background:var(--on-media);border:1px solid var(--accent);box-shadow:0 1px 3px rgba(0,0,0,.5)}
.ed-box-nw{left:0;top:0;cursor:nwse-resize}
.ed-box-n{left:50%;top:0;cursor:ns-resize}
.ed-box-ne{left:100%;top:0;cursor:nesw-resize}
.ed-box-e{left:100%;top:50%;cursor:ew-resize}
.ed-box-se{left:100%;top:100%;cursor:nwse-resize}
.ed-box-s{left:50%;top:100%;cursor:ns-resize}
.ed-box-sw{left:0;top:100%;cursor:nesw-resize}
.ed-box-w{left:0;top:50%;cursor:ew-resize}
/* The turn knob stands off the top edge, where it cannot be mistaken for a
   corner: a rotate that resizes is the classic confusion here. */
.ed-box-rot{left:50%;top:-26px;border-radius:999px;cursor:grab}
.ed-box-hint{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);margin:0;
  padding:6px 10px;border-radius:var(--radius-sm);font-size:12.5px;
  color:var(--on-media);background:var(--on-media-scrim);pointer-events:none}
.studio-lyrbox-bar{flex-wrap:wrap;gap:var(--space-3)}
/* ---- the history (U17) ---------------------------------------------------
   An undone step keeps its contrast and loses its dot's fill: it is still
   there to be clicked, and dimming it to 40% would say the opposite. */
.studio-hist{display:flex;flex-direction:column;gap:2px;padding:var(--space-4);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md);
  background:var(--surface);max-height:300px;overflow:auto}
.studio-hist-head{display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-4);
  margin-bottom:var(--space-2)}
.studio-hist-head h3{margin:0;font-size:13px}
.studio-hist-head .muted{font-size:11.5px}
.studio-hist-row{display:flex;align-items:center;gap:var(--space-4);width:100%;padding:5px 6px;
  border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text-primary);
  font:inherit;font-size:12.5px;text-align:left;cursor:pointer}
.studio-hist-row:hover{background:var(--surface-hover)}
.studio-hist-lab{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.studio-hist-dot{flex:none;width:8px;height:8px;border-radius:50%;background:var(--border-strong)}
.studio-hist-row.is-off .studio-hist-dot{background:transparent;
  border:1px solid var(--border-strong)}
/* ACCENT BUDGET: where you are standing, the one marked state in this list. */
.studio-hist-here{display:flex;align-items:center;gap:var(--space-4);margin:var(--space-1) 0;
  padding:5px 6px;border-radius:var(--radius-sm);background:var(--accent-muted);
  font-size:12.5px;font-weight:600;color:var(--accent-text)}
.studio-hist-here .studio-hist-dot{background:var(--accent)}
.studio-hist-none,.studio-hist-note{margin:var(--space-2) 0 0}
/* ---- the timeline tools (U18) -------------------------------------------
   A held tool changes what the next drag means, so the one in hand is the
   marked state -- and the cursor over the tracks changes with it, because a
   razor that looks like an arrow cuts something somebody did not mean. */
.studio-tools{display:inline-flex;gap:2px;margin-left:var(--space-4)}
.studio-tool{padding-inline:var(--space-5)}
/* ACCENT BUDGET: the "on" state of a segmented group, as elsewhere. */
.studio-tool.is-on{background:var(--accent);color:var(--text-on-accent);border-color:var(--accent)}
.studio-tl.is-razor .st-shot,.studio-tl.is-razor .st-shot *{cursor:crosshair}
.studio-marks{display:inline-flex;gap:2px;margin-left:var(--space-4)}
/* The export sheet: what survived the trip, and what did not. Monospace
   because it is a list to scan, not prose to read. */
.studio-sheet{margin:0;padding:var(--space-4);border-radius:var(--radius-sm);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle);
  font-family:var(--font-mono);font-size:11.5px;line-height:1.55;color:var(--text-secondary);
  white-space:pre-wrap;overflow-x:auto;max-height:280px}
.studio-shuttle{min-width:52px;color:var(--accent-text)}
/* In, out and the marks sit OVER the tracks rather than in a lane: they say
   where to look, and a lane of their own would read as part of the reel. */
.studio-io{position:absolute;left:0;top:0;height:16px;pointer-events:none;z-index:4}
.studio-io>*{pointer-events:auto}
.st-io-band{position:absolute;top:0;height:16px;background:rgba(77,159,255,.18);
  border-left:2px solid var(--accent);border-right:2px solid var(--accent)}
.st-io-edge{position:absolute;top:0;height:16px;padding:0 3px;font:700 10px var(--font-mono);
  line-height:16px;color:var(--text-on-accent);background:var(--accent)}
.st-io-b{transform:translateX(-100%)}
.st-mark{position:absolute;top:1px;width:0;height:0;padding:0;border:0;background:transparent;
  border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:9px solid var(--warn);margin-left:-5px;cursor:pointer}
.st-mark:hover{border-top-color:var(--text-primary)}
"""

CSS = CSS + EDITOR_CSS

# Issue #259: the Studio's layout. The side panel on demand, the player's transport as a media player's,
# the timeline's lanes and zoom, and the render status folded to a chip. After the editor's block so it
# wins where the two describe the same element.
LAYOUT_CSS = r"""
/* ---- the side panel, on demand ---- */
.studio-sidebtn{position:relative;padding-inline:var(--space-3)}
.studio-editor.side-off{grid-template-columns:minmax(0,1fr) 30px}
.studio-editor.side-off:not(.side-peek) .ed-side{display:none}
.studio-editor.side-off.side-peek{grid-template-columns:minmax(0,1fr) 380px}
.ed-side-edge{display:none;grid-column:2;grid-row:1;align-self:stretch;position:relative;
  width:calc(100% + var(--gutter));margin-inline-end:calc(var(--gutter) * -1);   /* to the window's edge */
  border-radius:var(--radius-sm) 0 0 var(--radius-sm);border:var(--border-hair) solid var(--border-subtle);border-right:0;
  background:var(--surface-sunken);cursor:w-resize;z-index:5}
.ed-side-tab{position:absolute;top:50%;left:0;right:0;transform:translateY(-50%);display:flex;flex-direction:column;
  align-items:center;gap:6px;color:var(--text-tertiary);font:600 11px/1 var(--font-text);letter-spacing:.06em;text-transform:uppercase}
.ed-side-tab span{writing-mode:vertical-rl}
.ed-side-edge:hover .ed-side-tab{color:var(--text-primary)}
.ed-side-hint{display:none;position:absolute;top:50%;right:calc(100% + 10px);transform:translateY(-50%);width:210px;
  padding:var(--space-3) var(--space-4);border-radius:var(--radius-md);background:var(--surface);
  border:var(--border-hair) solid var(--accent);box-shadow:var(--shadow-md);color:var(--text-primary);
  font:500 12px/1.4 var(--font-text);text-transform:none;letter-spacing:0;pointer-events:none}
.studio-editor.side-hint .ed-side-edge{border-color:var(--accent);animation:studio-edge-glow 1.1s ease-in-out 3}
.studio-editor.side-hint .ed-side-hint{display:block}
@keyframes studio-edge-glow{0%,100%{background:var(--surface-sunken)}50%{background:var(--accent-muted)}}
@media (prefers-reduced-motion:reduce){.studio-editor.side-hint .ed-side-edge{animation:none;background:var(--accent-muted)}}
.studio-editor.side-off:not(.side-peek) .ed-side-edge{display:block}
.studio-editor.side-off:not(.side-peek) .ed-side-edge:hover{background:var(--surface-hover)}
.studio-editor.side-off .ed-side{grid-column:2;grid-row:1}
@media (max-width:1100px){.ed-side-edge{display:none!important}}

/* ---- the render status, folded to a chip ---- */
.studio-sync-fold{margin-inline-start:auto;flex:none;display:inline-flex;align-items:center;justify-content:center;
  width:22px;height:22px;padding:0;border:0;border-radius:var(--radius-sm);background:transparent;
  color:var(--text-tertiary);cursor:pointer}
.studio-sync-fold:hover,.studio-sync-fold:focus-visible{background:var(--surface-hover);color:var(--text-primary)}
.studio-sync.is-folded{display:none}
.studio-chip{flex:none;align-self:flex-start;display:inline-flex;align-items:center;gap:var(--space-3);
  padding:3px 10px 3px 8px;border-radius:var(--radius-pill);border:var(--border-hair) solid var(--border-subtle);
  background:var(--surface-sunken);color:var(--text-secondary);font:500 12px/1.4 var(--font-text);cursor:pointer}
.studio-chip:hover,.studio-chip:focus-visible{border-color:var(--border-strong);color:var(--text-primary)}
.studio-chip.hide{display:none}
.studio-chip-dot{flex:none;display:inline-block;width:8px;height:8px;border-radius:var(--radius-pill);background:var(--text-tertiary)}
.studio-chip-dot.hide{display:none}
.studio-sidebtn .studio-chip-dot{position:absolute;top:3px;right:3px;width:7px;height:7px}
.studio-chip.is-ok .studio-chip-dot,.studio-chip-dot.is-ok{background:var(--ok)}
.studio-chip.is-busy .studio-chip-dot,.studio-chip-dot.is-busy{background:var(--warn);animation:studio-pulse 1.4s ease-in-out infinite}
.studio-chip.is-stale .studio-chip-dot,.studio-chip-dot.is-stale,
.studio-chip.is-timing .studio-chip-dot,.studio-chip-dot.is-timing{background:var(--warn)}
.studio-chip.is-bad .studio-chip-dot,.studio-chip-dot.is-bad{background:var(--danger)}
.studio-chip-text{font-variant-numeric:tabular-nums}
@keyframes studio-pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 var(--warn-muted)}50%{opacity:.35;box-shadow:0 0 6px 2px var(--warn-muted)}}
@media (prefers-reduced-motion:reduce){.studio-chip-dot.is-busy,.studio-chip.is-busy .studio-chip-dot{animation:none}}

/* ---- the player's transport ---- */
.ed-player-bar{flex:none;display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;
  gap:var(--space-4);padding:var(--space-3) var(--space-5);border-radius:var(--radius-md);
  background:var(--surface-sunken);border:var(--border-hair) solid var(--border-subtle)}
.ed-pb-left{display:flex;align-items:center;gap:var(--space-4);min-width:0}
.ed-pb-mid{display:flex;align-items:center;justify-content:center;gap:var(--space-4)}
.ed-pb-right{display:flex;align-items:center;justify-content:flex-end;min-width:0}
.ed-pb-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;padding:0;
  border:0;border-radius:var(--radius-pill);background:transparent;color:var(--text-secondary);cursor:pointer}
.ed-pb-btn svg{width:18px;height:18px;fill:currentColor}
.ed-pb-btn:hover,.ed-pb-btn:focus-visible{background:var(--surface-hover);color:var(--text-primary)}
.ed-pb-btn.is-play{width:44px;height:44px;background:var(--accent);color:var(--text-on-accent)}
.ed-pb-btn.is-play svg{width:22px;height:22px}
.ed-pb-btn.is-play:hover,.ed-pb-btn.is-play:focus-visible{background:var(--accent-hover)}
@media (max-width:759px){.ed-player-bar{grid-template-columns:1fr auto}.ed-pb-right{grid-column:1 / -1;justify-content:flex-start}}

/* ---- the timeline's toolbar ---- */
.studio-menu{position:relative}
.studio-menu>summary{list-style:none;cursor:pointer}
.studio-menu>summary::-webkit-details-marker{display:none}
.studio-menu>summary::after{content:"\25BE";margin-inline-start:6px;font-size:10px;color:var(--text-tertiary)}
.studio-menu-pop{position:absolute;z-index:30;top:calc(100% + 4px);left:0;min-width:180px;display:flex;flex-direction:column;
  gap:var(--space-3);padding:var(--space-4);border-radius:var(--radius-md);background:var(--surface);
  border:var(--border-hair) solid var(--border-subtle);box-shadow:var(--shadow-md);z-index:calc(var(--z-topbar) + 1)}
.studio-menu-sub{padding-inline-start:var(--space-6)}
.studio-menu-rule{width:100%;margin:0;border:0;border-top:var(--border-hair) solid var(--border-subtle)}
.studio-zoombtn{min-width:28px;padding-inline:0;font-size:16px;line-height:1}
.studio-help{position:relative;display:inline-flex;align-items:center;justify-content:center;flex:none;width:20px;height:20px;
  border-radius:var(--radius-pill);border:var(--border-hair) solid var(--border-subtle);color:var(--text-tertiary);
  font:600 12px/1 var(--font-text);cursor:help}
.studio-help:hover,.studio-help:focus-visible{color:var(--text-primary);border-color:var(--text-tertiary)}
.studio-help-pop{display:none;position:absolute;z-index:30;right:0;top:calc(100% + 6px);width:min(360px,70vw);padding:var(--space-4);
  border-radius:var(--radius-md);background:var(--surface);border:var(--border-hair) solid var(--border-subtle);
  box-shadow:var(--shadow-md);color:var(--text-secondary);font:400 12px/1.5 var(--font-text);
  text-align:left;white-space:normal}
.studio-help:hover .studio-help-pop,.studio-help:focus .studio-help-pop,.studio-help:focus-within .studio-help-pop{display:block}

/* a lane put away: its rows go, and the rest move up (studio_drawTimeline sets the rows) */
.studio-tracks.off-video .st-shot,.studio-tracks.off-video .st-introclip,.studio-tracks.off-video .st-lockband,
.studio-tracks.off-trans .st-tr,.studio-tracks.off-fx .st-fx,.studio-tracks.off-speed .st-speed,
.studio-tracks.off-text .st-text,.studio-tracks.off-music .st-music{display:none}
"""

LAYOUT_CSS += r"""
/* ---- the Make-a-reel Song step, in the Song tab's vocabulary ---- */
.gd-facts .sy-pill{background:var(--surface-hover);color:var(--text-primary);border-color:var(--border-subtle)}
.gd-facts .sy-pill b{margin-right:6px}
.gd-facts .sy-pill.is-len{background:var(--warn-muted);color:var(--warn);border-color:var(--warn-muted)}
.gd-facts .sy-pill.is-clips{background:var(--accent-muted);color:var(--accent-text);border-color:var(--accent-muted)}
.gd-drops .gd-howlong{margin-top:var(--space-2)}
.gd-drops .gd-seek{width:100%;margin-top:var(--space-2)}
.gd-transport.ed-player-bar{margin-top:var(--space-3)}
.sg-adv{margin-top:var(--space-3);border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md);background:var(--surface-sunken)}
.sg-adv>summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;padding:var(--space-3) var(--space-5);
  font:600 12px/1.3 var(--font-text);letter-spacing:.06em;text-transform:uppercase;color:var(--text-tertiary)}
.sg-adv>summary::-webkit-details-marker{display:none}
.sg-adv>summary::after{content:"\25BE";transition:transform var(--dur-fast)}
.sg-adv[open]>summary::after{transform:rotate(180deg)}
.sg-adv>summary:hover{color:var(--text-primary)}
.sg-adv .studio-sg-viewbar{padding:0 var(--space-5) var(--space-4);margin:0}
.sg-adv .studio-sg-lanes{padding:0 var(--space-5) var(--space-4)}
.gd-droptools{display:flex;gap:var(--space-1)}
.gd-vol input{width:110px}
"""
LAYOUT_CSS += r"""
/* ---- the reel's counts, as two pills; no play button on the picture (the player bar is the one) ---- */
.sy-chips{display:inline-flex;align-items:center;gap:var(--space-3);flex-wrap:wrap}
.sy-chips:empty{display:none}
.sy-pill{display:inline-block;padding:2px 10px;border-radius:var(--radius-pill);
  font:600 12px/1.6 var(--font-text);font-variant-numeric:tabular-nums;white-space:nowrap;
  border:var(--border-hair) solid transparent}
.sy-pill.is-clips{background:var(--accent-muted);color:var(--accent-text);border-color:var(--accent-muted)}
.sy-pill.is-kills{background:var(--ok-muted);color:var(--ok);border-color:var(--ok-muted)}
.sy-pill.is-hs{background:var(--warn-muted);color:var(--warn);border-color:var(--warn-muted)}
.studio-facts{display:inline-flex;align-items:center;gap:var(--space-3);margin:0}
.sy-pill.is-len{background:var(--warn-muted);color:var(--warn);border-color:var(--warn-muted)}
.sy-pill.is-style{background:var(--surface-hover);color:var(--text-primary);border-color:var(--border-subtle)}
.sy-pill.is-none{color:var(--text-tertiary);border-color:var(--border-subtle)}
#studio-video::-webkit-media-controls-play-button{display:none}
"""
LAYOUT_CSS += r"""
/* ---- the Song tab: two-word titles, a toolbar on each graph, the timeline's player bar ---- */
.sg-title{display:flex;align-items:center;gap:var(--space-3);margin:var(--space-4) 0 var(--space-2);
  font:600 13px/1.3 var(--font-text);color:var(--text-primary)}
.sg-title .studio-help-pop{left:0;right:auto}
.sg-title .sg-spacer{flex:1 1 auto}
.sg-zoom{font-size:16px}
.sg-range{display:inline-flex;align-items:center;gap:var(--space-3);padding:3px 14px;border-radius:var(--radius-pill);
  background:linear-gradient(135deg,var(--accent-muted),var(--surface-hover));border:var(--border-hair) solid var(--accent);
  color:var(--text-primary);font-size:12.5px;font-weight:600;letter-spacing:.02em;box-shadow:0 0 0 3px var(--accent-muted)}
.sg-range i{font-style:normal;color:var(--accent-text)}
.sg-bar{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2) var(--space-3);margin:var(--space-3) 0}
.sg-bar.hide{display:none}
.sg-lab{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--text-tertiary)}
.sg-time{min-width:58px;text-align:center;font-size:12.5px}
.sg-sep{width:1px;height:18px;background:var(--border-subtle);margin-inline:var(--space-2)}
.sg-spacer{flex:1 1 auto}
.sg-info{font-size:12px}
.sg-ic,.sg-tog{display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:28px;padding:0 6px;
  border:var(--border-hair) solid transparent;border-radius:var(--radius-sm);background:transparent;
  color:var(--text-secondary);font:500 15px/1 var(--font-text);cursor:pointer;position:relative}
.sg-ic:hover,.sg-tog:hover,.sg-ic:focus-visible{background:var(--surface-hover);color:var(--text-primary)}
.sg-ic:disabled{opacity:.4;cursor:default}
.sg-ic.is-main{background:var(--accent);color:var(--text-on-accent)}
.sg-ic.is-main:hover,.sg-ic.is-main:focus-visible{background:var(--accent-hover);color:var(--text-on-accent)}
.sg-tog input{position:absolute;opacity:0;inset:0;margin:0;cursor:pointer}
.sg-tog:has(input:checked){background:var(--accent-muted);color:var(--accent-text)}
.sg-tog:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:1px}
.ed-pb-right .sg-tog{margin-inline-end:var(--space-3)}
"""
CSS = CSS + LAYOUT_CSS

FACECAM_CSS = r"""
.studio-fc{display:flex;flex-direction:column;gap:var(--space-5)}
.studio-fc.hide{display:none}
.studio-fc-head{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--space-5);flex-wrap:wrap}
.studio-fc-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,1fr);gap:var(--space-5);align-items:start}
@media (max-width:1100px){.studio-fc-grid{grid-template-columns:1fr}}
.studio-fc-card{display:flex;flex-direction:column;gap:var(--space-4)}
.studio-fc-stage{position:relative;background:#000;border-radius:var(--radius-sm);overflow:hidden;cursor:crosshair;
  touch-action:none;user-select:none;line-height:0}
.studio-fc-stage img{width:100%;height:auto;display:block;pointer-events:none}
.studio-fc-links{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-fc-link{display:flex;align-items:center;justify-content:space-between;gap:var(--space-4);padding:var(--space-3) var(--space-4);
  border-radius:var(--radius-sm);border:var(--border-hair) solid var(--border-subtle);background:var(--surface-sunken)}
.studio-fc-link.is-on{border-color:var(--accent)}
.studio-fc-link-text{display:flex;flex-direction:column;gap:2px;min-width:0}
.studio-fc-sync{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-fc-sync.hide{display:none}
.studio-fc-pair{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-3)}
.studio-fc-pair figure{margin:0;display:flex;flex-direction:column;gap:4px}
.studio-fc-pair video{width:100%;aspect-ratio:16/9;background:#000;border-radius:var(--radius-sm)}
.studio-fc-pair figcaption{font-size:11.5px;color:var(--text-tertiary)}
.studio-fc-mockwrap{display:flex;justify-content:center;background:var(--surface-sunken);border-radius:var(--radius-sm);padding:var(--space-4)}
.studio-fc-mockwrap canvas{max-width:100%;max-height:52vh;border-radius:4px;box-shadow:var(--shadow-md);z-index:calc(var(--z-topbar) + 1)}

.studio-imp{width:min(1100px,calc(100vw - 48px))}
.studio-imp-body{max-width:none;display:grid;grid-template-columns:minmax(0,1.6fr) minmax(260px,1fr);gap:var(--space-5);align-items:start}
@media (max-width:899px){.studio-imp-body{grid-template-columns:1fr}}
.studio-imp-player{display:flex;flex-direction:column;gap:var(--space-3);min-width:0}
.studio-imp-player video{width:100%;max-height:56vh;background:#000;border-radius:var(--radius-sm)}
.studio-imp-lane{width:100%;height:46px;border-radius:var(--radius-sm);cursor:pointer;display:block}
.studio-imp-side{display:flex;flex-direction:column;gap:var(--space-3)}
.studio-imp-x{margin-left:4px;border:0;background:none;color:inherit;cursor:pointer;font-size:14px;line-height:1;padding:0 2px}
.btn.is-warn{color:var(--warn)}
"""

CSS = CSS + FACECAM_CSS

CSS += r"""
/* ==================================================== the style page, folded
   Level one is the preset; level two is every dial it already set. The fold
   carries a summary of what is inside it, because a control labelled only
   "Advanced" makes people open it to find out whether it matters -- and the
   aim is that most finish without opening anything. */
.clip-adv{margin-top:calc(var(--space-5) * -1)}
.clip-adv-toggle{
  display:flex;align-items:center;gap:var(--space-3);width:100%;
  padding:var(--space-4);border-radius:var(--radius-md);
  border:var(--border-hair) dashed var(--border-subtle);
  background:transparent;color:var(--text-secondary);
  font:600 13px/1 inherit;cursor:pointer;text-align:left;
}
.clip-adv-toggle:hover{background:var(--surface-hover);color:var(--text-primary)}
.clip-adv-caret{transition:transform .15s ease;font-size:11px}
.clip-adv-toggle[aria-expanded="true"] .clip-adv-caret{transform:rotate(90deg)}
.clip-adv-sum{margin-inline-start:auto;font-weight:400;font-size:12.5px}
.clip-adv-body{margin-top:var(--space-5)}
.clip-adv-body .clip-grid{
  padding:var(--space-5);border-radius:var(--radius-lg);
  background:var(--surface-active);
}

/* ============================================= choosing a part of a recording
   THE WHOLE RECORDING IS NOT PLAYABLE HERE and cannot be made so: AutoStream
   records fragmented mp4 with no seek index, so a browser asked to jump an
   hour into one reads from the start of a file that can be 47 GB. The
   filmstrip is how you move around the whole thing; the player holds a small
   seekable copy of whichever part is being asked about. */
.clip-part{display:flex;flex-direction:column;gap:var(--space-5)}
.clip-part-view{
  position:relative;width:100%;aspect-ratio:16/9;max-height:52vh;
  border-radius:var(--radius-lg);overflow:hidden;background:#000;
  border:var(--border-hair) solid var(--border-subtle);
}
.clip-part-video{width:100%;height:100%;object-fit:contain;display:block;background:#000}
.clip-part-empty{
  position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:var(--space-2);
  text-align:center;padding:var(--space-6);color:var(--text-secondary);
}
.clip-part-empty p{margin:0}
.clip-part-bar{
  display:flex;align-items:center;justify-content:space-between;
  gap:var(--space-4);flex-wrap:wrap;
}
.clip-part-times{display:flex;gap:var(--space-6)}
.clip-part-time{display:flex;flex-direction:column;gap:2px;line-height:1.1}
.clip-part-time b{font-size:19px;font-variant-numeric:tabular-nums}
.clip-part-time .muted{font-size:11px;text-transform:uppercase;letter-spacing:.07em}
@media (max-width:620px){
  .clip-part-view{max-height:34vh}
  .clip-part-times{gap:var(--space-4)}
  .clip-part-time b{font-size:16px}
}
"""

# ONE REEL'S TIMING, AND WHERE IT STANDS (ui/studio.py: studio_flowDraw, studio_badgeDraw). The stale
# banner has to be the thing nobody misses on the Song tab and beside Render: a warn edge and wash, the
# way out as the page's primary button, and a slow glow on it -- which stops, and becomes a plain ring,
# for anyone who has asked their system for less motion.
CSS += r"""
.studio-flow-host:empty{display:none}
.studio-flow{display:flex;flex-direction:column;gap:var(--space-3);padding:var(--space-4) var(--space-5);
  border:var(--border-hair) solid var(--border);border-left:4px solid var(--border-strong);
  border-radius:var(--radius-md);background:var(--surface);margin:0 0 var(--space-4)}
.studio-flow p{margin:0}
.studio-flow ul{margin:0;padding-left:1.2em;display:flex;flex-direction:column;gap:2px;font-size:12.5px}
.studio-flow-head{font:650 14px/1.35 var(--font-text);color:var(--text-primary)}
.studio-flow.is-stale{border-left-color:var(--warn);background:var(--warn-muted)}
.studio-flow.is-bad{border-left-color:var(--danger);background:var(--danger-muted)}
.studio-flow.is-busy{border-left-color:var(--accent)}
.studio-flow.is-prop{border-left-color:var(--accent);background:var(--accent-muted)}
.studio-flow.is-ask{border-left-color:var(--accent)}
.studio-flow-acts{display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center}
.studio-flow-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--space-3)}
.studio-flow-cols b{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-secondary)}
.studio-flow-why{font-size:12.5px;color:var(--text-primary);font-weight:600}
.studio-flow-room{font-size:12.5px;display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center}
.studio-flow-choice{display:flex;flex-direction:column;gap:var(--space-2);padding:var(--space-3) 0;
  border-top:var(--border-hair) solid var(--border-subtle)}
.studio-slot{padding:var(--space-3) var(--space-4);margin:var(--space-2) 0}
.studio-slot-head{display:flex;justify-content:space-between;align-items:center;gap:var(--space-2)}
.studio-flow ul.studio-slot-list{list-style:none;padding:0;gap:var(--space-1);max-height:260px;overflow:auto}
.studio-slot-list li{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,auto) auto;gap:var(--space-2);align-items:center}
.studio-slot-list li .mono{font-size:11px;white-space:normal;text-align:right}
.studio-flow-choice button{align-self:flex-start}
.studio-attn{position:relative;box-shadow:0 0 0 2px var(--accent);animation:studio-attn var(--dur-pulse) var(--ease-standard) infinite}
@keyframes studio-attn{0%,100%{box-shadow:0 0 0 2px var(--accent),0 0 0 0 var(--accent-muted)}
  50%{box-shadow:0 0 0 2px var(--accent),0 0 0 7px var(--accent-muted)}}
@media (prefers-reduced-motion:reduce){.studio-attn{animation:none;box-shadow:0 0 0 2px var(--accent),0 0 0 5px var(--accent-muted)}}
.studio-attn:disabled{animation:none;box-shadow:none}
.studio-badge{display:inline-flex;align-items:center;gap:6px;height:var(--h-control-sm);padding:0 10px;
  border-radius:var(--radius-pill);border:var(--border-hair) solid var(--border);font:600 12px/1 var(--font-text);
  color:var(--text-secondary);white-space:nowrap}
.studio-badge:empty{display:none}
.studio-badge-dot{width:var(--size-dot);height:var(--size-dot);border-radius:var(--radius-pill);background:var(--text-tertiary)}
.studio-badge.is-stale,.studio-badge.is-changed{border-color:var(--warn);color:var(--text-primary);background:var(--warn-muted)}
.studio-badge.is-stale .studio-badge-dot,.studio-badge.is-changed .studio-badge-dot{background:var(--warn)}
.studio-badge.is-failed{border-color:var(--danger);color:var(--text-primary);background:var(--danger-muted)}
.studio-badge.is-failed .studio-badge-dot{background:var(--danger)}
.studio-badge.is-rendered,.studio-badge.is-ready{border-color:var(--ok);color:var(--text-primary)}
.studio-badge.is-rendered .studio-badge-dot,.studio-badge.is-ready .studio-badge-dot{background:var(--ok)}
.studio-badge.is-planning,.studio-badge.is-rendering{border-color:var(--accent);color:var(--text-primary)}
.studio-badge.is-planning .studio-badge-dot,.studio-badge.is-rendering .studio-badge-dot{background:var(--accent)}
.studio-sync.is-timing{border-left-color:var(--warn);background:var(--warn-muted)}
.studio-sync.is-timing .studio-sync-dot{background:var(--warn)}
.studio-acts3{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2)}
.studio-ver-head{margin-top:var(--space-4)}
.studio-ver-row{display:flex;flex-direction:column;gap:2px;padding:var(--space-2) 0;border-top:var(--border-hair) solid var(--border-subtle)}
.studio-ver-row.is-current .studio-ver-name b{color:var(--accent-text)}
.studio-ver-now{font-size:11px;color:var(--ok)}
.studio-ver-bad{font-size:11px;color:var(--danger)}
.studio-ver-acts{display:flex;gap:var(--space-2);flex-wrap:wrap}
.mk-says{margin:0 0 var(--space-2);font-size:12px;color:var(--text-secondary)}
.mk-says:empty{display:none}
.mk-group{margin:0 0 var(--space-3);font:650 18px/1.2 var(--font-display);color:var(--text-primary)}
.mk-bar-name{margin:0}
.mk-bar-input{max-width:260px}
.reel-chip.is-hand{border-color:var(--accent)}
.reel-chip.is-ghost{opacity:.55;border-style:dashed}
.studio-mk-dropsbox.is-flash{outline:2px solid var(--warn);outline-offset:4px;border-radius:var(--radius-md)}
"""
