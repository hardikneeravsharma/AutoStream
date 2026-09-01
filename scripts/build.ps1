<#
    AutoStream - build AutoStream.exe

        powershell -ExecutionPolicy Bypass -File scripts\build.ps1
        powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -Clean

    Output: dist\AutoStream\AutoStream.exe  (a folder - keep it together)

    Your existing config\ and secrets\ are copied into the build so the exe
    works immediately. Rebuilding never overwrites them.

    NOTE: this script deliberately does NOT use $ErrorActionPreference='Stop'.
    Native commands that write to stderr (pip, PyInstaller, and a failing
    `import` probe) would otherwise raise NativeCommandError and abort the
    build. Exit codes are checked explicitly instead.
#>
param([switch]$Clean, [switch]$Dist)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($msg)  { Write-Host "  [--] $msg" }
function Write-Ok($msg)    { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Write-Bad($msg)   { Write-Host "  [!!] $msg" -ForegroundColor Red }
function Write-Warn($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Yellow }

# Run a native command, echo its output, return its exit code.
# 2>&1 keeps stderr out of PowerShell's error stream.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments, [switch]$Echo)
    $global:LASTEXITCODE = 0
    if ($Echo) {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "       $_" }
    } else {
        & $Exe @Arguments 2>&1 | Out-Null
    }
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  Building AutoStream.exe" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

$vpy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Bad ".venv not found. Run scripts\install.ps1 first."
    exit 1
}

# ---- 1. PyInstaller --------------------------------------------------
# This probe is EXPECTED to fail when PyInstaller is absent - it prints a
# traceback to stderr. Invoke-Native swallows that and returns the code.
if ((Invoke-Native $vpy @("-c", "import PyInstaller")) -ne 0) {
    Write-Step "installing PyInstaller (one time, ~30s)..."
    if ((Invoke-Native $vpy @("-m", "pip", "install", "pyinstaller", "--quiet") -Echo) -ne 0) {
        Write-Bad "could not install PyInstaller"
        exit 1
    }
    if ((Invoke-Native $vpy @("-c", "import PyInstaller")) -ne 0) {
        Write-Bad "PyInstaller installed but will not import"
        exit 1
    }
}
Write-Ok "PyInstaller ready"

# ---- 2. sanity: does the app import at all? --------------------------
if ((Invoke-Native $vpy @("-c", "import autostream.__main__, autostream.web, autostream.panel")) -ne 0) {
    Write-Bad "the package does not import - fix that before building:"
    Invoke-Native $vpy @("-c", "import autostream.__main__, autostream.web, autostream.panel") -Echo | Out-Null
    exit 1
}
Write-Ok "package imports cleanly"

# A running copy of the previous build keeps logs\autostream.log open, and
# PyInstaller clears dist\ before it writes. Without this check that surfaces as
# a shutil.rmtree traceback ending in WinError 32, which says nothing about the
# actual problem being "the app you are rebuilding is still running".
$running = @(Get-Process -Name "AutoStream" -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    Write-Warn "AutoStream is running ($($running.Count) process) and holds files in dist\"
    Write-Step "closing it..."
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    if (@(Get-Process -Name "AutoStream" -ErrorAction SilentlyContinue).Count -gt 0) {
        Write-Bad "could not close AutoStream - quit it from the tray and re-run"
        exit 1
    }
    Write-Ok "closed"
}

if ($Clean) {
    Write-Step "cleaning build\ and dist\..."
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

# ---- 2b. keep the LIVE installation's own files -----------------------
# PyInstaller clears dist\AutoStream, and what used to be restored afterwards
# came from the REPO. So every rebuild silently replaced the running app's
# settings with the repo's copy, and deleted its log.
#
# That is not a theoretical loss. The log is the only record of what the app
# did, and losing it on every build meant a folder that vanished during a
# session could not be accounted for afterwards -- there was nothing left to
# read. paths.py already says exactly this about clips and history: anything
# inside the application folder is destroyed by a rebuild.
#
# So the live copies are taken first and put back first; the repo only fills
# what the live install did not have.
$carry = Join-Path $Root "build\_carry"
Remove-Item -Recurse -Force $carry -ErrorAction SilentlyContinue
$live = Join-Path $Root "dist\AutoStream"
if (Test-Path $live) {
    New-Item -ItemType Directory -Path $carry -Force | Out-Null
    foreach ($d in @("config", "secrets", "logs")) {
        $src = Join-Path $live $d
        if (Test-Path $src) { Copy-Item $src (Join-Path $carry $d) -Recurse -Force }
    }
    $st = Join-Path $live "state.json"
    if (Test-Path $st) { Copy-Item $st (Join-Path $carry "state.json") -Force }
    Write-Ok "kept the live install's config, secrets, logs and state.json"
}

# ---- 3. build --------------------------------------------------------
Write-Step "building (2-4 minutes, output below)..."
$code = Invoke-Native $vpy @("-m", "PyInstaller", "autostream.spec", "--noconfirm", "--log-level", "WARN") -Echo
if ($code -ne 0) {
    Write-Bad "PyInstaller exited with code $code - see the output above"
    exit 1
}

$out = Join-Path $Root "dist\AutoStream"
$exe = Join-Path $out "AutoStream.exe"
if (-not (Test-Path $exe)) {
    Write-Bad "build reported success but $exe is missing"
    exit 1
}
Write-Ok "built $exe"

# ---- 4a. carry over config / secrets (never overwrite) ---------------
# Runs BEFORE the -Dist block, not after it. PyInstaller clears dist\AutoStream
# on every build, so a -Dist run used to rebuild the local install, package it,
# and exit without ever restoring config\ and secrets\ -- leaving the user's own
# installation unable to start as a side effect of packaging one for a friend.
# The share copy is scrubbed of all of this anyway, and asserts it afterwards.
function Restore-LocalConfig {
    foreach ($d in @("config", "secrets", "logs")) {
        $dst = Join-Path $out $d
        if (-not (Test-Path $dst)) { New-Item -ItemType Directory -Path $dst | Out-Null }
    }
    # THE LIVE INSTALL'S OWN FILES FIRST. Everything below copies from the REPO
    # and skips what already exists, so putting these back here is what makes
    # the repo the fallback rather than the winner. Without it a rebuild handed
    # the running app the repo's settings and an empty log.
    if (Test-Path $carry) {
        foreach ($d in @("config", "secrets", "logs")) {
            $src = Join-Path $carry $d
            if (Test-Path $src) {
                Copy-Item (Join-Path $src "*") (Join-Path $out $d) -Recurse -Force
            }
        }
        $st = Join-Path $carry "state.json"
        if (Test-Path $st) { Copy-Item $st (Join-Path $out "state.json") -Force }
        Write-Ok "restored the live install's config, secrets, logs and state.json"
    }
    # clip_profiles.yaml is the user's own calibration work; losing it on a
    # rebuild would mean re-teaching every game. Its templates come along too.
    $calib = Join-Path $Root "config\clip_templates"
    if (Test-Path $calib) {
        $dstCalib = Join-Path $out "config\clip_templates"
        if (-not (Test-Path $dstCalib)) {
            Copy-Item $calib $dstCalib -Recurse
            Write-Ok "copied config\clip_templates"
        }
    }
    # apps.yaml belongs here too: PyInstaller clears dist\AutoStream on every
    # build, so leaving it out silently empties the Library page each rebuild.
    #
    # streamelements.json for the same reason as token.json: it is a credential
    # the APP stored, not one anybody can paste back from memory, and losing it
    # on a rebuild silently unhooks the screen savers -- which in turn makes
    # Pause end a live broadcast instead of parking it on the card.
    foreach ($f in @("config\config.yaml", "config\games.yaml", "config\apps.yaml",
                     "config\index.cache.json", "config\clip_profiles.yaml",
                     "secrets\client_secret.json", "secrets\token.json",
                     "secrets\streamelements.json")) {
        $src = Join-Path $Root $f
        $dst = Join-Path $out $f
        if ((Test-Path $src) -and (-not (Test-Path $dst))) {
            Copy-Item $src $dst
            Write-Ok "copied $f"
        } elseif (Test-Path $dst) {
            Write-Host "  [--] kept existing $f" -ForegroundColor DarkGray
        }
    }
}
Restore-LocalConfig

# ---- 4b. DIST mode: a clean, shareable package with NO credentials ---
if ($Dist) {
    $share = Join-Path $Root "dist\AutoStream-share"
    Remove-Item -Recurse -Force $share -ErrorAction SilentlyContinue
    Copy-Item $out $share -Recurse

    # Nuke anything personal. Belt and braces: delete the folders, then assert.
    Remove-Item -Recurse -Force (Join-Path $share "secrets") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $share "logs")    -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $share "state.json")       -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $share "config")  -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path (Join-Path $share "secrets") | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $share "logs")    | Out-Null

    # ...then put back the ONE config file that belongs to nobody. The public
    # game index is 10,000 executables mapped to game names, fetched from a
    # public endpoint on every start anyway -- shipping it means a new install
    # names games correctly on its very first launch and before it has been
    # online. Everything else in config\ is personal:
    #
    #   config.yaml         the channel, the stream key's home, the overlays
    #   games.yaml          the IN-GAME NAME the kill feed is read for
    #   clip_profiles.yaml  calibration, including that name and the HUD colour
    #   apps.yaml           which games are installed on this machine
    #   clip_templates\     pixel patches cut from the user's own footage
    #
    # paths.seed_config() copies whatever survives here into the user's own
    # config folder on first run, and never over anything already there.
    $seedDir = Join-Path $share "config"
    New-Item -ItemType Directory -Path $seedDir | Out-Null
    $index = Join-Path $out "config\index.cache.json"
    if (Test-Path $index) {
        Copy-Item $index (Join-Path $seedDir "index.cache.json")
        Write-Ok "shipped the public game index as a default"
    }

    # Verify: no personal file survived anywhere in the package. games.yaml and
    # clip_profiles.yaml are on this list because both carry the in-game name
    # the kill feed is read for, which is a real identity and not a setting.
    $leaks = Get-ChildItem $share -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "token|client_secret|state\.json" -or
                       $_.Name -eq "config.yaml" -or $_.Name -eq "apps.yaml" -or
                       $_.Name -eq "games.yaml" -or
                       $_.Name -eq "clip_profiles.yaml" -or
                       $_.Name -eq "streamelements.json" }
    if ($leaks) {
        Write-Bad "ABORTING - credential files found in the share package:"
        $leaks | ForEach-Object { Write-Host "       $($_.FullName)" -ForegroundColor Red }
        exit 1
    }

    # Zipped by scripts\make_zip.py rather than Compress-Archive. That cmdlet
    # reports a per-file failure to the error stream and then carries on, so it
    # can leave an archive missing _internal\base_library.zip -- which Defender
    # routinely holds a lock on for a moment after PyInstaller writes it -- and
    # still look like it worked. The lock is transient, so the fix is to retry
    # the file, then verify every entry against the source listing.
    $zip = Join-Path $Root "dist\AutoStream-share.zip"
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    if ((Invoke-Native $vpy @("scripts\make_zip.py", $share, $zip) -Echo) -ne 0) {
        Write-Bad "ABORTING - could not produce a complete archive"
        Remove-Item -Force $zip -ErrorAction SilentlyContinue
        exit 1
    }
    $zmb = "{0:N0}" -f ((Get-Item $zip).Length / 1MB)

    Write-Host ""
    Write-Ok "shareable package verified clean - no tokens, no config"
    Write-Host "       $zip  ($zmb MB)"
    Write-Host ""
    Write-Host "  Your friend unzips it, runs AutoStream.exe, and the setup" -ForegroundColor White
    Write-Host "  wizard opens in a window. They need their own Google Cloud" -ForegroundColor White
    Write-Host "  project - the wizard walks them through it." -ForegroundColor White
    Write-Host ""
    exit 0
}

$size = "{0:N0}" -f ((Get-ChildItem $out -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  Done - $size MB in dist\AutoStream\" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Test it:" -ForegroundColor White
Write-Host "    .\dist\AutoStream\AutoStream.exe"
Write-Host ""
Write-Host "  It runs windowless - look for the tray icon and the panel." -ForegroundColor DarkGray
Write-Host "  If nothing appears: dist\AutoStream\logs\crash.log" -ForegroundColor DarkGray
Write-Host ""
Write-Warn "SmartScreen warns on first run (unsigned): More info -> Run anyway"
Write-Host ""
Write-Host "  Start on login:" -ForegroundColor White
Write-Host "    powershell -File scripts\register_task.ps1 -Exe"
Write-Host ""
Write-Host "  Package for a friend (no credentials):" -ForegroundColor White
Write-Host "    powershell -File scripts\build.ps1 -Dist"
Write-Host ""
