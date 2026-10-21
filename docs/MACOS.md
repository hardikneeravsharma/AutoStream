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
**`AutoStream-<version>-macos-arm64.dmg`** for Apple Silicon (M1 and later), or
**`AutoStream-<version>-macos-x86_64.dmg`** for an Intel Mac. Open it and drag AutoStream to
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
scripts/macos/build.sh --dist     # and AutoStream-macos-<arch>.dmg + .sha256 (renamed with the version on release)
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
| `autostream/macos/updates.py` | The app updating itself: picks this Mac's `.dmg`, stages the new app, and swaps it in after the quit. |
| `packaging/macos/` | `autostream-macos.spec`, `launcher.py`, `make_icns.py`. |
| `scripts/macos/` | `install.sh`, `build.sh`. |
| `.github/workflows/release.yml` | The release: a pushed `v*` tag builds Windows and both Macs on GitHub's runners and publishes them together. |
| `requirements-macos.txt` | The packages the Mac build needs, without the streaming half. |
| `tests/macos/` | Tests for all of the above. They run on every platform by pretending `sys.platform`. `mac_skips.py` lists the Windows-behaviour tests that are skipped on a Mac, each with its reason. |

The shared files that gained a `darwin` branch are `paths.py`, `window.py`,
`__main__.py`, `webui.py`, `setup_flow.py`, `clips/tools.py`, `clips/deps.py`,
`clips/overlay.py`, `clips/mark.py`, `clips/studio.py`, `clips/highlight.py` and
`clips/cs2_demo.py`. The UI changes are in `ui/shell.py` and `ui/setup.py`, which drop
pages and choices when `/api/bootstrap` says to, and in `ui/clips.py`, which shows the
server's install text. On Windows the bootstrap carries none of those keys, so every
fallback is the old value.

## How a release is made

Push an annotated version tag on `main`. Its first line is the title, and the rest
becomes the notes:

```bash
git tag -a v1.79.0 -m "v1.79.0: what it is" -m "Notes, in markdown."
git push origin v1.79.0
```

`.github/workflows/release.yml` builds Windows (`build.ps1 -Dist`) and both Macs on
GitHub's runners. `scripts/release_assets.py` then names every file the same way,
version first, and writes its `.sha256` (issue #206):

| File | What it is |
|---|---|
| `AutoStream-<v>-windows-x64-setup.exe` | the Windows installer |
| `AutoStream-<v>-windows-x64.zip` | the portable Windows copy |
| `AutoStream-<v>-macos-arm64.dmg` | Apple Silicon |
| `AutoStream-<v>-macos-x86_64.dmg` | Intel Mac |
| `AutoStream-<v>-setup.exe` | **until v1.80.0 only**: the installer again, under the only name installs up to v1.78.1 look for, so they can still update themselves. `LEGACY_UNTIL` in the script ends it. |

The release is published with every file attached at once. The tag must match
`__version__`, or nothing is built. If a release for that tag already exists, the
files it is missing are uploaded to it instead. To retry after a runner failure:
**Actions > Release > Run workflow**, and enter the tag.

## How the app updates itself

**Settings > Updates** works the same on both platforms: it checks GitHub, downloads
this machine's file and verifies its `.sha256`. On a Mac, **Install and restart** then:
- mounts the `.dmg` and copies the new app next to the running one;
- quits, and a small script swaps the two, deletes the old one and reopens AutoStream;
- puts the old app back if the swap fails.

Gatekeeper only checks files a browser has flagged as downloaded, so an update the app
fetched itself opens without "Open Anyway". Only the first install needs it. Because
the app is ad-hoc signed and that signature changes with every build, macOS may ask
again for access to Documents or Desktop after an update. The app needs write access
to its own folder; without it, it says so and points to the `.dmg`. Macs on v1.78.1
have to download v1.78.2 by hand once: that version's updater refused everything
(issue #205).

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
