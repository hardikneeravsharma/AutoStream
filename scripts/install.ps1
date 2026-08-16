<#
    AutoStream - Phase C installer
    Creates the venv, installs dependencies, finds your client_secret.json.

    Run from the project root:
        powershell -ExecutionPolicy Bypass -File scripts\install.ps1

    If auto-detection picks the wrong Python, point at one explicitly:
        powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -PythonPath "C:\Python312\python.exe"
#>
param([string]$PythonPath)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  AutoStream installer" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Find a Python 3.11+ ------------------------------------------

function Get-PyVersion {
    param([string]$Exe, [string[]]$PreArgs = @())
    try {
        $out = & $Exe @PreArgs --version 2>&1 | Out-String
    } catch {
        return $null
    }
    if ($out -match "Python\s+(\d+)\.(\d+)") {
        return [pscustomobject]@{
            Major = [int]$Matches[1]
            Minor = [int]$Matches[2]
            Text  = $out.Trim()
        }
    }
    return $null
}

$pyExe = $null
$pyArgs = @()
$seen = @()

if ($PythonPath) {
    if (-not (Test-Path $PythonPath)) {
        Write-Host "  [!!] -PythonPath '$PythonPath' does not exist" -ForegroundColor Red
        exit 1
    }
    $v = Get-PyVersion -Exe $PythonPath
    if (-not $v) {
        Write-Host "  [!!] '$PythonPath' did not report a version" -ForegroundColor Red
        exit 1
    }
    if ($v.Major -lt 3 -or ($v.Major -eq 3 -and $v.Minor -lt 11)) {
        Write-Host "  [!!] $($v.Text) is too old - need 3.11 or newer" -ForegroundColor Red
        exit 1
    }
    $pyExe = $PythonPath
} else {
    # (exe, extra args) pairs, best first
    $candidates = @(
        @{ Exe = "py";      Args = @("-3.13") },
        @{ Exe = "py";      Args = @("-3.12") },
        @{ Exe = "py";      Args = @("-3.11") },
        @{ Exe = "py";      Args = @()        },
        @{ Exe = "python3"; Args = @()        },
        @{ Exe = "python";  Args = @()        }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        $v = Get-PyVersion -Exe $c.Exe -PreArgs $c.Args
        $label = (@($c.Exe) + $c.Args) -join " "
        if (-not $v) {
            $seen += "$label -> no version reported (Microsoft Store stub?)"
            continue
        }
        $seen += "$label -> $($v.Text)"
        if ($v.Major -eq 3 -and $v.Minor -ge 11) {
            $pyExe = $c.Exe
            $pyArgs = $c.Args
            break
        }
    }
}

if (-not $pyExe) {
    Write-Host "  [!!] No Python 3.11+ found." -ForegroundColor Red
    Write-Host ""
    if ($seen.Count -gt 0) {
        Write-Host "       What I did find:" -ForegroundColor Yellow
        foreach ($s in $seen) { Write-Host "         $s" -ForegroundColor Yellow }
    } else {
        Write-Host "       No python, python3 or py command on PATH at all." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "       Fix: install Python 3.12 from https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host "       IMPORTANT: tick 'Add python.exe to PATH' on the first screen." -ForegroundColor Cyan
    Write-Host "       Then open a NEW PowerShell window and re-run this script." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "       Already have one somewhere unusual (conda, etc)? Pass it directly:" -ForegroundColor Cyan
    Write-Host "         .\scripts\install.ps1 -PythonPath `"C:\path\to\python.exe`"" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

$pyLabel = (@($pyExe) + $pyArgs) -join " "
Write-Host "  [ok] using $pyLabel" -ForegroundColor Green

# ---- 2. venv ---------------------------------------------------------
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "  [--] creating virtual environment..."
    & $pyExe @pyArgs -m venv .venv
}
if (-not (Test-Path $vpy)) {
    Write-Host "  [!!] venv creation failed" -ForegroundColor Red
    Write-Host "       Try:  $pyLabel -m venv .venv" -ForegroundColor Yellow
    exit 1
}
Write-Host "  [ok] venv ready" -ForegroundColor Green

# ---- 3. dependencies -------------------------------------------------
Write-Host "  [--] installing dependencies (this takes a minute)..."
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [!!] pip install failed - re-running verbosely so you can see why" -ForegroundColor Red
    & $vpy -m pip install -r requirements.txt
    exit 1
}
Write-Host "  [ok] dependencies installed" -ForegroundColor Green

# quick import check - catches a broken pywin32 install early
& $vpy -c "import psutil, yaml, obsws_python, googleapiclient, requests; print('imports ok')" 2>&1 |
    ForEach-Object { Write-Host "       $_" }

# ---- 4. folders ------------------------------------------------------
foreach ($d in @("secrets", "logs", "config")) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

# ---- 5. client_secret.json ------------------------------------------
$target = Join-Path $Root "secrets\client_secret.json"
if (Test-Path $target) {
    Write-Host "  [ok] client_secret.json already in place" -ForegroundColor Green
} else {
    $found = Get-ChildItem -Path "$env:USERPROFILE\Downloads","$env:USERPROFILE\Desktop" `
        -Filter "client_secret*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) {
        Copy-Item $found.FullName $target
        Write-Host "  [ok] copied $($found.Name) -> secrets\client_secret.json" -ForegroundColor Green
    } else {
        Write-Host "  [!!] client_secret.json not found in Downloads or Desktop." -ForegroundColor Yellow
        Write-Host "       Download it from Google Cloud Console -> Clients," -ForegroundColor Yellow
        Write-Host "       then save it to: $target" -ForegroundColor Yellow
    }
}

# ---- 6. OBS path -----------------------------------------------------
$obsGuesses = @(
    "C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    "C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"
)
$obs = $obsGuesses | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($obs) {
    Write-Host "  [ok] OBS found at $obs" -ForegroundColor Green
} else {
    Write-Host "  [!!] OBS not found at the usual paths - set obs.path in config\config.yaml" -ForegroundColor Yellow
}

# ---- 7. OBS websocket password --------------------------------------
Write-Host ""
Write-Host "  In OBS: Tools -> WebSocket Server Settings" -ForegroundColor Cyan
Write-Host "    [x] Enable WebSocket server, port 4455, set a password," -ForegroundColor Cyan
Write-Host "        then click 'Show Connect Info' to copy it." -ForegroundColor Cyan
Write-Host ""
$pw = Read-Host "  Paste your obs-websocket password (blank to skip)"
if ($pw) {
    [Environment]::SetEnvironmentVariable("AUTOSTREAM_OBS_PW", $pw, "User")
    $env:AUTOSTREAM_OBS_PW = $pw
    Write-Host "  [ok] saved as user environment variable AUTOSTREAM_OBS_PW" -ForegroundColor Green
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  Done. Next:" -ForegroundColor Cyan
Write-Host "    .\.venv\Scripts\python.exe -m autostream setup" -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
