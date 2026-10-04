# Running the browser tests

Everything here drives **the built app** — `dist\AutoStream\AutoStream.exe` —
in headless Chromium. If you only need the offline suite, none of this applies:
that is `.\.venv\Scripts\python.exe -m pytest -q` and it takes about a minute.

## The one thing that trips everyone up

**The app must not be running.** The harness refuses to start a second copy,
because it cannot tell a spare instance from one that is live on YouTube or
halfway through cutting clips. Every test skips with:

```
AutoStream is already running; quit it first
```

Ask it to quit rather than killing it — this works even when it is elevated,
which `Stop-Process` is not:

```powershell
$t = (Select-String -Path "$env:LOCALAPPDATA\AutoStream\config\config.yaml" `
        -Pattern 'web_token:\s*(.+)').Matches[0].Groups[1].Value.Trim()
Invoke-RestMethod -Uri "http://127.0.0.1:8787/api/cmd?k=$t" -Method Post `
    -Body '{"command":"quit"}' -ContentType 'application/json'
```

Check `/api/status` first. Quitting destroys a clip job in progress and ends a
live broadcast; say so rather than doing it silently.

## Prerequisites

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
```

A build must exist at `dist\AutoStream\AutoStream.exe`, and it must be newer
than whatever you are testing — the tests drive the **build**, not the source
tree, so an edit you have not rebuilt is not under test:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

A plain build runs the offline tiers only and takes about three minutes.
`-Dist` adds the real-footage tier and takes closer to an hour.

## Running them

All of it:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\verify -m ui -q -p no:randomly
```

One file, which is what you usually want:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\verify\test_ui_sweep.py -m ui -q -p no:randomly
```

`-m ui` is required: these are marked `ui` and **deselected by default**, so a
plain `pytest -q` silently runs none of them. `-p no:randomly` keeps the
journey's steps in order — it is written to run top to bottom.

Through the build script instead, as CI does:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify.ps1 -Release
```

Only `-Release` runs tiers 5–7. `-Dist` does not, which is why a `-Dist` build
can pass having never booted the binary it just made.

## The files, and what each is for

| File | Asks | Time |
|---|---|---|
| `test_ui_playwright.py` | The big Studio flows, and that media really plays | ~4 min |
| `test_ui_sweep.py` | Presses every control it can reach; nothing errors | ~1.5 min |
| `test_ui_clip_stages.py` | The Clips page's six stages, button by button | ~1 min |
| `test_ui_journey.py` | One person's whole path, in order, ending in a real run | ~5 min+ |
| `test_ui_setup.py` | The first screen a new user sees | seconds |

`docs/UI-SCENARIOS.md` is the catalogue these are written from, including the
scenarios that have **no** test yet. Read it before adding one, so you add a
gap rather than a duplicate.

## How they are built

- **`appd.py`** starts the built exe against a throwaway `AUTOSTREAM_HOME` on
  a free port, with YouTube off. Nothing of the user's is touched and nothing
  leaves the machine. `appd.NO_WINDOW` is the flag that keeps subprocesses
  from flashing a console over whatever the person at the keyboard is doing —
  **use it for every `subprocess.run` you add**.
- **`Watched`** (in `test_ui_playwright.py`) collects console errors, uncaught
  exceptions and any response ≥400, and `clean()` asserts all three are empty.
  Reuse it; most UI bugs here announce themselves as a console error nobody
  was listening for.
- Tests seed their own footage with ffmpeg. A recording must be **over two
  minutes** or the Clips page correctly hides the part stage and the test is
  asserting against a screen that is right to be absent.

## Writing one

Three things that have each cost an afternoon:

1. **Wait for `state="attached"`, not visible.** A view carries `is-active`
   while its contents are still empty, and Playwright calls a zero-height
   element invisible — so waiting for visibility waits for data.
2. **Playwright will not click a disabled or covered control.** If what you
   are testing is the handler rather than the pointer, dispatch it:
   `page.eval_on_selector(sel, "e => e.click()")`.
3. **The status poll reloads real data every two seconds.** Rows you put on
   the page from the test are wiped between statements, so make every
   assertion inside one `page.evaluate`.

## When a sweep says a control "could not be pressed"

That is a finding about the pointer, not the handler — usually a panel still
animating or something overlapping. The sweep already falls back to a DOM
click. If both fail, the control is genuinely unreachable and worth looking at.

## Coverage, honestly

The sweep reaches **117 of the 190** `data-act` controls the source declares.
The rest sit behind a dialog, a selection, or a job that has actually run.
`REACHED_FLOOR` in `test_ui_sweep.py` pins 117 so that a page which quietly
stops rendering fails there instead of passing with less under test. Raise it
when coverage improves; never lower it without saying what stopped being
reachable.
