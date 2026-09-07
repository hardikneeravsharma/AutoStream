<#
    AutoStream - prove the build works before it goes out.

        powershell -ExecutionPolicy Bypass -File scripts\verify.ps1 -Quick
        powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
        powershell -ExecutionPolicy Bypass -File scripts\verify.ps1 -Release

    -Quick    tiers 1-3. Offline, needs nothing installed, about 25 seconds.
              This is the one to run while working.
    (none)    tiers 1-4. Adds the clip detectors, measured against a reviewed
              baseline on real footage. Ten to fifteen minutes.
    -Release  tiers 1-6. Adds the built binary and a real private broadcast.
              This is what build.ps1 -Dist runs.

    Tiers 5 and 6 touch things outside this process, so each one says what it
    is about to do before it does it, and is skipped rather than failed when
    its prerequisite is absent. A tier that cannot run is not a tier that
    passed: the summary says which is which.

    Same convention as build.ps1: no $ErrorActionPreference='Stop', because
    pytest writes to stderr and that would abort the run before it started.
    Exit codes are checked explicitly.
#>
param(
    [switch]$Quick,
    [switch]$Release,
    # Tier 6 creates and deletes a real broadcast on the configured channel.
    # It never runs without this, not even under -Release, unless -Live is
    # given too. Costs quota; needs OBS running.
    [switch]$Live,
    [switch]$FailFast
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($msg)  { Write-Host "  [--] $msg" }
function Write-Ok($msg)    { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Write-Bad($msg)   { Write-Host "  [!!] $msg" -ForegroundColor Red }
function Write-Warn($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Skip($msg)  { Write-Host "  [--] $msg" -ForegroundColor DarkGray }

$vpy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Bad "no .venv - run scripts\install.ps1 first"
    exit 1
}

$MediaDir = if ($env:AUTOSTREAM_TESTDATA) { $env:AUTOSTREAM_TESTDATA }
            else { "C:\autostream-testdata" }
$BuiltExe = Join-Path $Root "dist\AutoStream\AutoStream.exe"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  Verifying AutoStream" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

$results = @()
$started = Get-Date

function Invoke-Tier {
    param([string]$Name, [string]$Marker, [string]$Path = "tests")

    Write-Step "$Name ..."
    $args = @("-m", "pytest", $Path, "-q", "--no-header")
    if ($Marker) { $args += @("-m", $Marker) }
    if ($FailFast) { $args += "-x" }

    $t0 = Get-Date
    & $vpy @args 2>&1 | ForEach-Object { Write-Host "       $_" }
    $code = $LASTEXITCODE
    $secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)

    if ($code -eq 0) {
        Write-Ok "$Name passed (${secs}s)"
        $script:results += [pscustomobject]@{ Tier = $Name; State = "passed"; Seconds = $secs }
    } elseif ($code -eq 5) {
        # pytest's "no tests collected". A tier with nothing in it yet is not
        # a failure, but it must not read as a pass either.
        Write-Skip "$Name - nothing to run yet"
        $script:results += [pscustomobject]@{ Tier = $Name; State = "empty"; Seconds = $secs }
    } else {
        Write-Bad "$Name FAILED (${secs}s)"
        $script:results += [pscustomobject]@{ Tier = $Name; State = "FAILED"; Seconds = $secs }
    }
    return $code
}

function Skip-Tier {
    param([string]$Name, [string]$Why)
    Write-Skip "$Name - skipped: $Why"
    $script:results += [pscustomobject]@{ Tier = $Name; State = "skipped"; Seconds = 0 }
}

# ---- tiers 1-3: offline. Always. -------------------------------------
#
# One pytest run, because they share a process and the whole thing is 25
# seconds. Splitting them would cost more in interpreter startup than it
# would buy in a prettier summary.
Invoke-Tier -Name "tiers 1-3  offline: units, flows, state machine" -Marker "" | Out-Null

# ---- tier 4: the clip detectors, measured ----------------------------
if (-not $Quick) {
    if (Test-Path $MediaDir) {
        Write-Step "tier 4 will scan real footage from $MediaDir - this takes minutes"
        Invoke-Tier -Name "tier 4     clip detectors vs baseline" -Marker "media" | Out-Null
    } else {
        Skip-Tier -Name "tier 4     clip detectors vs baseline" `
                  -Why "no corpus at $MediaDir (build one: $vpy tests\verify\corpus.py build)"
    }
} else {
    Skip-Tier -Name "tier 4     clip detectors vs baseline" -Why "-Quick"
}

# ---- tier 5: the built binary ----------------------------------------
if ($Release) {
    $running = @(Get-Process -Name "AutoStream" -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        # Never kill it. It may be mid-broadcast or mid-clip-job, and this
        # script's job is to check the build, not to end someone's stream.
        Skip-Tier -Name "tier 5     the built binary boots" `
                  -Why "AutoStream is running; quit it first (POST /api/cmd {""command"":""quit""})"
    } elseif (-not (Test-Path $BuiltExe)) {
        Skip-Tier -Name "tier 5     the built binary boots" -Why "no build at $BuiltExe"
    } else {
        Invoke-Tier -Name "tier 5     the built binary boots" -Marker "build" | Out-Null
    }
} else {
    Skip-Tier -Name "tier 5     the built binary boots" -Why "not -Release"
}

# ---- tier 6: real OBS, real private broadcast ------------------------
if ($Release -and $Live) {
    Write-Warn "tier 6 creates a REAL private broadcast on the configured channel"
    Write-Warn "       and deletes it again. It spends YouTube quota."
    Invoke-Tier -Name "tier 6     real OBS and a real broadcast" -Marker "live" | Out-Null
} elseif ($Release) {
    Skip-Tier -Name "tier 6     real OBS and a real broadcast" `
              -Why "needs -Live as well; it spends quota and needs OBS running"
} else {
    Skip-Tier -Name "tier 6     real OBS and a real broadcast" -Why "not -Release"
}

# ---- the summary -----------------------------------------------------
$total = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
Write-Host ""
Write-Host "--------------------------------------------------------------"
foreach ($r in $results) {
    $colour = switch ($r.State) {
        "passed"  { "Green" }
        "FAILED"  { "Red" }
        default   { "DarkGray" }
    }
    Write-Host ("  {0,-46} {1}" -f $r.Tier, $r.State) -ForegroundColor $colour
}
Write-Host "--------------------------------------------------------------"

$failed = @($results | Where-Object { $_.State -eq "FAILED" })
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Bad "verify FAILED in ${total}s - do not ship this build"
    exit 1
}

$skipped = @($results | Where-Object { $_.State -eq "skipped" -or $_.State -eq "empty" })
Write-Host ""
if ($skipped.Count -gt 0) {
    Write-Ok "verify passed in ${total}s ($($skipped.Count) tier(s) not run - see above)"
} else {
    Write-Ok "verify passed in ${total}s - every tier ran"
}
exit 0
