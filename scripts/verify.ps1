<#
    AutoStream - prove the build works before it goes out.

        powershell -ExecutionPolicy Bypass -File scripts\verify.ps1 -Quick
        powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
        powershell -ExecutionPolicy Bypass -File scripts\verify.ps1 -Release

    -Quick    tiers 1-3. Offline, needs nothing installed, about 25 seconds.
              This is the one to run while working.
    (none)    tiers 1-4. Adds the clip detectors, measured against a reviewed
              baseline on real footage. Ten to fifteen minutes.
    -Release  tiers 1-7. Adds the built binary, the browser, and (with -Live)
              a real private broadcast. This is what build.ps1 -Dist runs.

    TIER 4 IS ASKED FOR, NOT ASSUMED. It decodes real footage and runs real
    encodes, and it is most of the wall-clock time of a release build -- so
    it runs when something it measures has changed and is skipped, with the
    reason printed, when nothing has. The line is autostream\clips\ plus
    tier 4's own files: that is the pipeline it exists to measure, and a
    change to the dashboard, the settings schema, OBS or the platform seam
    cannot alter where a kill is found or where a shot lands.

    IT ERRS TOWARDS RUNNING. No git, no tag, a detached head, a git command
    that fails -- any question it cannot answer is answered by running it.
    The cost of a needless half hour is a slow build; the cost of skipping
    it when it mattered is shipping a detector nobody measured.

    -Media    run tier 4 whatever the diff says.
    -NoMedia  skip tier 4 whatever the diff says.

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
    # Tier 4, forced on or off. Neither given means "decide from the diff";
    # see Test-MediaNeeded.
    [switch]$Media,
    [switch]$NoMedia,
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

# ---- has tier 4 anything to measure? ---------------------------------
#
# Tier 4 is most of the wall clock of a release build: it decodes real
# footage and runs real encodes. Spending half an hour of it to prove that
# a change to the settings page did not move a detector is half an hour
# spent proving something nobody touched.
#
# WHAT IT MEASURES is the clip pipeline -- where a kill is found, and where
# a shot lands in a rendered reel. So the question is whether anything under
# autostream\clips\ has changed, plus tier 4's own files. Nothing else in
# the app can move those numbers: the dashboard, the settings schema, OBS,
# the platform seam and the installer all sit on the other side of it.
#
# SINCE THE LAST RELEASE TAG, not since the last commit. The question is
# "has the pipeline changed since the last build that was measured", and on
# a branch with six commits the last commit is the wrong baseline -- it
# would skip tier 4 for a branch that rewrote the detector in its first.
#
# UNCOMMITTED WORK COUNTS, because the build is made from the working tree
# and not from HEAD. A detector edited and not yet committed is a detector
# this build contains.
$MediaPaths = @("autostream/clips/",
                "tests/verify/test_media.py",
                "tests/verify/test_reel_flow.py",
                "tests/verify/test_studio_render.py",
                "tests/verify/corpus.py")

function Test-MediaNeeded {
    <#
      -> @{ Needed = $bool; Why = "<one line>"; Files = @(...) }

      EVERY UNCERTAIN ANSWER IS "RUN IT". No git, no tag, a git call that
      fails: the cost of a needless half hour is a slow build, and the cost
      of being wrong the other way is shipping a detector nobody measured.
    #>
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        return @{ Needed = $true; Files = @()
                  Why = "git is not on PATH, so nothing can say what changed" }
    }
    $inRepo = (& git rev-parse --is-inside-work-tree 2>$null)
    if ($LASTEXITCODE -ne 0 -or $inRepo -ne "true") {
        return @{ Needed = $true; Files = @()
                  Why = "not a git checkout, so nothing can say what changed" }
    }

    $base = (& git describe --tags --abbrev=0 --match "v*" 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $base) {
        return @{ Needed = $true; Files = @()
                  Why = "no release tag to compare against" }
    }
    $base = $base.Trim()

    $changed = @(& git diff --name-only $base 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return @{ Needed = $true; Files = @()
                  Why = "git diff against $base failed" }
    }
    # Uncommitted and untracked too. The porcelain line is two status
    # columns, a space and the path; a rename is "old -> new" and it is the
    # NEW name that is in the tree being built.
    $dirty = @(& git status --porcelain 2>$null) | ForEach-Object {
        $path = $_.Substring(3)
        if ($path -match ' -> ') { $path = ($path -split ' -> ')[-1] }
        $path.Trim('"')
    }
    $changed = @(@($changed) + @($dirty) | Where-Object { $_ } | Sort-Object -Unique)

    $hits = @($changed | Where-Object {
        $f = $_.Replace("\", "/")
        @($MediaPaths | Where-Object { $f.StartsWith($_) }).Count -gt 0
    })

    if ($hits.Count -gt 0) {
        return @{ Needed = $true; Files = $hits
                  Why = "$($hits.Count) file(s) under the clip pipeline changed since $base" }
    }
    return @{ Needed = $false; Files = @()
              Why = "nothing under the clip pipeline changed since $base ($($changed.Count) other file(s) did)" }
}

# ---- tiers 1-3: offline. Always. -------------------------------------
#
# One pytest run, because they share a process and the whole thing is 25
# seconds. Splitting them would cost more in interpreter startup than it
# would buy in a prettier summary.
Invoke-Tier -Name "tiers 1-3  offline: units, flows, state machine" -Marker "" | Out-Null

# ---- tier 4: the clip detectors, measured ----------------------------
if ($Quick) {
    Skip-Tier -Name "tier 4     clip detectors vs baseline" -Why "-Quick"
} elseif ($NoMedia -and -not $Media) {
    Skip-Tier -Name "tier 4     clip detectors vs baseline" -Why "-NoMedia"
} elseif (-not (Test-Path $MediaDir)) {
    Skip-Tier -Name "tier 4     clip detectors vs baseline" `
              -Why "no corpus at $MediaDir (build one: $vpy tests\verify\corpus.py build)"
} else {
    # -Media beats the diff AND -NoMedia: an explicit "run it" is somebody
    # saying they know something a file list cannot.
    if ($Media) { $ask = @{ Needed = $true; Why = "-Media"; Files = @() } }
    else        { $ask = Test-MediaNeeded }

    if (-not $ask.Needed) {
        Skip-Tier -Name "tier 4     clip detectors vs baseline" -Why $ask.Why
        Write-Skip "           run it anyway with -Media"
    } else {
        Write-Step "tier 4: $($ask.Why)"
        # NAMED, NOT COUNTED. Half an hour is long enough that the reader
        # deserves to see which file bought it, and a path that surprises
        # them is how a mis-scoped change gets noticed.
        foreach ($f in @($ask.Files | Select-Object -First 12)) {
            Write-Host "         $f" -ForegroundColor DarkGray
        }
        if ($ask.Files.Count -gt 12) {
            Write-Host "         ... and $($ask.Files.Count - 12) more" -ForegroundColor DarkGray
        }
        Write-Step "tier 4 will scan real footage from $MediaDir - this takes minutes"
        Invoke-Tier -Name "tier 4     clip detectors vs baseline" -Marker "media" | Out-Null
    }
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

# ---- tier 7: the built app in a real browser -------------------------
#
# The only tier that sees what the PAGE does with an answer: console errors,
# requests that come back refused, and whether a media element can actually
# play. A greyed-out play button is invisible to every tier above this one.
if ($Release) {
    $running = @(Get-Process -Name "AutoStream" -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        Skip-Tier -Name "tier 7     the built app in a browser" `
                  -Why "AutoStream is running; quit it first (POST /api/cmd {""command"":""quit""})"
    } elseif (-not (Test-Path $BuiltExe)) {
        Skip-Tier -Name "tier 7     the built app in a browser" -Why "no build at $BuiltExe"
    } else {
        $chromium = & $vpy -c "import playwright; print('ok')" 2>$null
        if ($chromium -ne "ok") {
            Skip-Tier -Name "tier 7     the built app in a browser" `
                      -Why "playwright is not installed (pip install playwright; python -m playwright install chromium)"
        } else {
            Invoke-Tier -Name "tier 7     the built app in a browser" -Marker "ui" | Out-Null
        }
    }
} else {
    Skip-Tier -Name "tier 7     the built app in a browser" -Why "not -Release"
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
