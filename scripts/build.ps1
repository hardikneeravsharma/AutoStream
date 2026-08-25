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

    # Verify: no credential-shaped file survived anywhere in the package.
    $leaks = Get-ChildItem $share -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "token|client_secret|state\.json" -or
                       $_.Name -eq "config.yaml" -or $_.Name -eq "apps.yaml" }
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
