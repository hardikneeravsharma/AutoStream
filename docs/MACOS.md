# AutoStream on macOS: the clipper and the Studio

The Mac build is for **clipping footage you already have**: a recording made on your
Windows PC, copied across, and turned into clips, verticals, a montage and reels. It
does not stream, and it never needs a game installed. It runs on Apple Silicon and
Intel Macs, macOS 11 or later. This is issue
[#193](https://github.com/hardikneeravsharma/AutoStream/issues/193).

## What works, and what does not

| On a Mac | |
|---|---|
| **Clips**: *Clip a video file*, the filmstrip range, calibration, planning and cutting, 16:9 masters, 1080x1920 verticals, montage, promo reel, captions and branding | yes |
| **Detectors on a recording**: template match, VALORANT feed bars, CS2 kill feed (Tesseract), CS2 card tally, CS2 `.dem` parsing and sync (`demoparser2`), loudness (`any-game`) | yes |
| **Studio**: clip library, reel planning on the beat grid, timeline editor, two-stage render with cached shots, song editor, YouTube audio download, intros, deleting clips | yes |
| **Extras**: spoken hooks (Kokoro, on the CPU), beat-synced reels | yes |
| Hardware encoding | **VideoToolbox**, with libx264 if it fails |
| Streaming, the game watcher, OBS, recording setup, screen savers, thumbnails, YouTube sign-in and uploads, chat | no: not started |
| The tray icon, the overlay, the kill switch, start-at-login | no: Windows only |
| Anything that needs the **game installed**: VALORANT's match record from the Riot client, fetching a CS2 demo from a match code | no: read the screen instead, and copy the `.dem` across from the PC |

The **Dashboard** and **Library** pages are not shown, and Settings shows only the
sections that mean something on a Mac. The first-run wizard offers only *Just make
clips*. Closing the window quits the app, because there is no tray to hide in. If a clip
job or a reel render is still running, it asks you first.

## Download

From the [latest release](https://github.com/hardikneeravsharma/AutoStream/releases/latest):
**`AutoStream-macos-arm64.dmg`** for Apple Silicon (M1 and later), or
**`AutoStream-macos-x86_64.dmg`** for an Intel Mac. Open it and drag AutoStream to
Applications. You still need ffmpeg: `brew install ffmpeg-full`.

The app is not notarised by Apple yet, so the first time you open it macOS refuses.
Go to **System Settings > Privacy & Security**, scroll down to the message about
AutoStream, and click **Open Anyway**. You only need to do this once.

## Install from source

```bash
brew install python ffmpeg-full          # ffmpeg-full, NOT ffmpeg - see below
scripts/macos/install.sh                 # .venv + requirements-macos.txt
.venv/bin/python -m autostream run
```

The install script also checks your ffmpeg and tells you if it is the wrong one.
`scripts/macos/install.sh --dev` adds the test suite's requirements.

### Why `ffmpeg-full`

Homebrew's plain `ffmpeg` formula is built **without libass and freetype**. It has no
`ass` filter and no `drawtext`. Clips still cut, but they come out without captions,
lyrics, the handle or the spoken-hook subtitle. You can check with `ffmpeg -filters`.
`ffmpeg-full` has both. It is keg-only, so it is not on your PATH, but AutoStream looks
for it there first (`/opt/homebrew/opt/ffmpeg-full/bin`, or `/usr/local/opt/...` on an
Intel Mac). It also brings Tesseract along. The Clips page warns you if the ffmpeg it
found cannot draw text.

## Build the .app

```bash
scripts/macos/build.sh            # offline suite, then dist/macos/AutoStream.app
scripts/macos/build.sh --dist     # and AutoStream-macos-<arch>.dmg + .sha256
```

The output goes to `dist/macos/` and `build/macos/`. The Windows build uses
`dist/AutoStream`, so the two never overwrite each other. The app is ad-hoc signed and
not notarised, so a downloaded copy needs **Open Anyway** the first time (see
Download, above). To sign it with a real identity, set `AUTOSTREAM_CODESIGN`. To build for the
other architecture, set `AUTOSTREAM_ARCH=x86_64`.

## Where it keeps things

| | |
|---|---|
| Settings, secrets, logs | `~/Library/Application Support/AutoStream` (the built app); the repo itself when run from source |
| Clips, session history, the voice model | `~/Movies/AutoStream` |
| A crash in the built app | `~/Library/Logs/AutoStream/crash.log` |

`AUTOSTREAM_HOME`, `AUTOSTREAM_VIDEO_HOME` and `AUTOSTREAM_MODELS` override these, just
as on Windows.

## How the port is laid out

Rule for this port: **no Windows code path changes.** All macOS behaviour lives in new
files. Shared code reaches it only from behind `sys.platform == "darwin"`.

| Path | What it is |
|---|---|
| `autostream/macos/launch.py` | `autostream run` on a Mac: the server and the window, with no engine. `__main__.cmd_run` hands over to it. |
| `autostream/macos/window.py` | `MacWindow`: closing quits, minimise goes to the Dock, and a close while busy asks first. Also screen geometry from AppKit. |
| `autostream/macos/paths.py` | `~/Library/Application Support` and `~/Movies`. |
| `autostream/macos/tools.py` | Finding ffmpeg, ffprobe and Tesseract: the `ffmpeg-full` keg first, and the Homebrew prefixes that a Finder launch does not have on PATH. Also checks for the text filters. |
| `autostream/macos/encode.py` | VideoToolbox encode (quality mode on Apple Silicon, bitrate on Intel) and decode. |
| `autostream/macos/fonts.py` | The macOS (or bundled) file for every font the renderers ask Windows for. |
| `autostream/macos/deps.py` | Homebrew install commands, the in-app Homebrew installer, and the text-filter warning. |
| `autostream/macos/dialogs.py` | The file picker: pywebview's sheet, or AppleScript when there is no window. Never Tk. |
| `autostream/macos/shell.py` | `open` / `open -R`, for *Reveal* and *Open log*. |
| `autostream/macos/features.py` | What is unavailable and why; the pages and settings that are hidden. |
| `autostream/macos/updates.py` | The in-app updater says it is not available, rather than downloading a Windows build. |
| `packaging/macos/` | `autostream-macos.spec`, `launcher.py`, `make_icns.py`. |
| `scripts/macos/` | `install.sh`, `build.sh`. |
| `.github/workflows/macos-release.yml` | Builds both `.dmg`s on GitHub's Mac runners and attaches them to each published release. Can also be run by hand for an existing tag. |
| `requirements-macos.txt` | The packages the Mac build needs, without the streaming half. |
| `tests/macos/` | Tests for all of the above. They run on every platform by pretending `sys.platform`. `windows_only.py` lists the Windows-behaviour tests that are skipped on a Mac, each with its reason. |

The shared files that gained a `darwin` branch are `paths.py`, `window.py`,
`__main__.py`, `webui.py`, `setup_flow.py`, `clips/tools.py`, `clips/deps.py`,
`clips/overlay.py`, `clips/mark.py`, `clips/studio.py`, `clips/highlight.py` and
`clips/cs2_demo.py`. The UI changes are in `ui/shell.py` and `ui/setup.py`, which drop
pages and choices when `/api/bootstrap` says to, and in `ui/clips.py`, which shows the
server's install text. On Windows the bootstrap carries none of those keys, so every
fallback is the old value.

## How a release gets its Mac build

Publishing a GitHub release, which still happens from the Windows machine, starts
`.github/workflows/macos-release.yml`. It builds on an Apple Silicon runner and an
Intel runner, runs `tests/macos`, and uploads `AutoStream-macos-arm64.dmg` and
`AutoStream-macos-x86_64.dmg` with their `.sha256` files. The names carry no version,
so `releases/latest/download/AutoStream-macos-arm64.dmg` always points at the newest
build. To give an older release its Mac build: **Actions > macOS release > Run
workflow**, and enter the tag.

## Testing on a Mac

```bash
.venv/bin/python -m pytest -q                                   # offline suite
AUTOSTREAM_VERIFY_SOURCE=1 .venv/bin/python -m pytest tests/verify -m ui -q -p no:randomly
.venv/bin/python -m playwright install chromium                 # once, for the line above
```

The browser tier was written against the Windows app. On a Mac, the tests for the
Dashboard, Library, OBS, streaming platforms and the setup wizard's streaming path fail
by design, because those pages are not there. The Clips and Studio tests are the ones
that apply.
