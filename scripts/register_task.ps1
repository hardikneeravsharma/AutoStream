<#
    AutoStream - Phase E: run on login as a Scheduled Task.

    A Scheduled Task, NOT a Windows Service: a service runs in session 0 and
    cannot see the desktop, the foreground window, or OBS.

        powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
        powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Exe
        powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Remove

    -Exe     point the task at dist\AutoStream\AutoStream.exe instead of the venv
    -Remove  unregister the task
#>
param([switch]$Remove, [switch]$Exe)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "AutoStream"

function Write-Step($msg) { Write-Host "  [--] $msg" }
function Write-Ok($msg)   { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Write-Bad($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Red }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  [ok] scheduled task '$TaskName' removed" -ForegroundColor Green
    exit 0
}

if ($Exe) {
    $target = Join-Path $Root "dist\AutoStream\AutoStream.exe"
    if (-not (Test-Path $target)) {
        Write-Host "  [!!] $target not found. Run scripts\build.ps1 first." -ForegroundColor Red
        exit 1
    }
    $workdir = Split-Path -Parent $target
    # Global flags go BEFORE the subcommand. "run --quiet" makes argparse exit
    # with code 2, which surfaces as LastTaskResult 0x2 and reads exactly like
    # "file not found" - the task appears registered and simply never runs.
    $argline = "--quiet run"
} else {
    $target = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $target)) {
        Write-Host "  [!!] $target not found. Run scripts\install.ps1 first." -ForegroundColor Red
        exit 1
    }
    $workdir = $Root
    $argline = "-m autostream --quiet run"
}

# pythonw.exe / a windowed exe = no console window
$action = New-ScheduledTaskAction -Execute $target -Argument $argline -WorkingDirectory $workdir

# 45s delay lets the network, Steam and the GPU driver settle first
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT45S"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "Starts a YouTube live stream automatically when a game launches." | Out-Null

Write-Host ""
Write-Host "  [ok] scheduled task '$TaskName' registered" -ForegroundColor Green
Write-Host "       runs : $target $argline"
Write-Host "       in   : $workdir"
Write-Host "       when : at logon + 45s"
Write-Host ""

# ---- verify it actually runs -----------------------------------------
# Registering only proves the XML was accepted. The failure mode this guards
# against - a bad argument line - leaves a perfectly valid task that dies
# instantly and windowless, with nothing on screen to tell you.
Write-Step "starting it now to verify..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName $TaskName

$leaf = Split-Path -Leaf $target
$proc = $null
foreach ($i in 1..20) {
    Start-Sleep -Seconds 1
    $proc = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($leaf)) -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $target }
    if ($proc) { break }
    $res = (Get-ScheduledTaskInfo -TaskName $TaskName).LastTaskResult
    # 0x41301 = still running. Anything else this early means it exited.
    if ($res -ne 267009 -and $res -ne 0 -and $i -gt 3) { break }
}

$info = Get-ScheduledTaskInfo -TaskName $TaskName
if ($proc) {
    Write-Ok "running - PID $($proc.Id)"
    Write-Host ""
    Write-Host "  It survives logoff and starts 45s after every logon." -ForegroundColor White
    Write-Host "  Look for the tray icon; the window opens from there." -ForegroundColor DarkGray
} else {
    Write-Bad "the task was registered but the app is NOT running"
    Write-Host ("       LastTaskResult : 0x{0:X}" -f $info.LastTaskResult) -ForegroundColor Red
    if ($info.LastTaskResult -eq 2) {
        Write-Warn "0x2 = bad argument line or missing exe (argparse exits 2 on a bad flag)"
    }
    Write-Host "       check logs\autostream.log and logs\crash.log in:" -ForegroundColor Red
    Write-Host "       $workdir" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "  Check it:   .\.venv\Scripts\python.exe -m autostream status" -ForegroundColor Cyan
Write-Host "  Stop it:    Stop-ScheduledTask -TaskName $TaskName" -ForegroundColor Cyan
Write-Host "  Remove it:  powershell -File scripts\register_task.ps1 -Remove" -ForegroundColor Cyan
Write-Host ""
