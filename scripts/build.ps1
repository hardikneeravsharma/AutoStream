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

# ---- 4a. DIST mode: a clean, shareable package with NO credentials ---
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

    $zip = Join-Path $Root "dist\AutoStream-share.zip"
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $share "*") -DestinationPath $zip

    # Compress-Archive reports a per-file error to the error stream and then
    # carries on, so the archive can be missing files while the script looks
    # like it succeeded. Defender holding a lock on a freshly written
    # base_library.zip is the usual cause, and that one file is the difference
    # between a working exe and one that will not start. Verify entry-by-entry.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $srcFiles = Get-ChildItem $share -Recurse -File
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
    $entries = @($archive.Entries | ForEach-Object { $_.FullName -replace '\\', '/' })
    $archive.Dispose()
    $expected = @($srcFiles | ForEach-Object {
        $_.FullName.Substring($share.Length + 1) -replace '\\', '/' })
    $missing = @($expected | Where-Object { $entries -notcontains $_ })
    if ($missing.Count -gt 0) {
        Write-Bad "ABORTING - $($missing.Count) file(s) missing from the archive:"
        $missing | Select-Object -First 10 | ForEach-Object { Write-Host "       $_" -ForegroundColor Red }
        Write-Warn "usually an antivirus lock. Close AutoStream and run this again."
        Remove-Item -Force $zip -ErrorAction SilentlyContinue
        exit 1
    }
    Write-Ok "archive verified - $($entries.Count) entries, nothing missing"
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

# ---- 4b. carry over config / secrets (never overwrite) ---------------
foreach ($d in @("config", "secrets", "logs")) {
    $dst = Join-Path $out $d
    if (-not (Test-Path $dst)) { New-Item -ItemType Directory -Path $dst | Out-Null }
}
# apps.yaml belongs here too: PyInstaller clears dist\AutoStream on every build,
# so leaving it out silently empties the Library page after each rebuild.
foreach ($f in @("config\config.yaml", "config\games.yaml", "config\apps.yaml",
                 "config\index.cache.json",
                 "secrets\client_secret.json", "secrets\token.json")) {
    $src = Join-Path $Root $f
    $dst = Join-Path $out $f
    if ((Test-Path $src) -and (-not (Test-Path $dst))) {
        Copy-Item $src $dst
        Write-Ok "copied $f"
    } elseif (Test-Path $dst) {
        Write-Host "  [--] kept existing $f" -ForegroundColor DarkGray
    }
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
