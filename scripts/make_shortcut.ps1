<#
.SYNOPSIS
    Create (or refresh) the AutoStream Desktop and Start Menu shortcuts.

.DESCRIPTION
    Points at dist\AutoStream\AutoStream.exe and uses the icon embedded in it.

    WorkingDirectory matters more than it looks. AutoStream resolves config\,
    secrets\, logs\ and state.json relative to the exe, and a shortcut launched
    with the wrong working directory would have it reading a different
    installation's settings -- or creating an empty one.

.PARAMETER Exe
    Override the target. Defaults to dist\AutoStream\AutoStream.exe.

.PARAMETER Remove
    Delete the shortcuts instead of creating them.

.PARAMETER NoStartMenu
    Desktop only.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
    powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string] $Exe,
    [switch] $Remove,
    [switch] $NoStartMenu
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Write-Ok  ($m) { Write-Host "  [ok] $m" -ForegroundColor Green }
function Write-Bad ($m) { Write-Host "  [!!] $m" -ForegroundColor Red }

$desktop   = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"

$targets = @(Join-Path $desktop "AutoStream.lnk")
if (-not $NoStartMenu) { $targets += (Join-Path $startMenu "AutoStream.lnk") }

if ($Remove) {
    foreach ($lnk in $targets) {
        if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Ok "removed $lnk" }
        else { Write-Host "  [--] not there: $lnk" -ForegroundColor DarkGray }
    }
    exit 0
}

if (-not $Exe) { $Exe = Join-Path $Root "dist\AutoStream\AutoStream.exe" }
if (-not (Test-Path $Exe)) {
    Write-Bad "no exe at $Exe"
    Write-Host "       Build it first:  powershell -File scripts\build.ps1" -ForegroundColor Yellow
    exit 1
}
$Exe = (Resolve-Path $Exe).Path
$workdir = Split-Path -Parent $Exe

# The exe carries the icon as resource 0, so pointing at "<exe>,0" means the
# shortcut follows a rebuilt icon automatically. A separate .ico path would go
# stale the moment the file moved.
$iconRef = "$Exe,0"

$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in $targets) {
    $parent = Split-Path -Parent $lnk
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath       = $Exe
    $s.WorkingDirectory = $workdir
    $s.IconLocation     = $iconRef
    $s.Description      = "AutoStream - game-aware YouTube live streaming"
    $s.WindowStyle      = 1
    $s.Save()
    Write-Ok "wrote $lnk"
}

# Explorer caches shortcut icons aggressively and will happily keep showing the
# previous one -- or a blank page -- until something tells it otherwise.
# SHCNE_ASSOCCHANGED (0x08000000) is the documented nudge.
try {
    Add-Type -Namespace Win32 -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, uint flags, System.IntPtr a, System.IntPtr b);
'@ -ErrorAction Stop
    [Win32.Shell]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
    Write-Ok "asked Explorer to refresh its icon cache"
} catch {
    Write-Host "  [--] could not refresh the icon cache; sign out and back in if the" -ForegroundColor DarkGray
    Write-Host "       shortcut still shows the old icon" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  target : $Exe"
Write-Host "  workdir: $workdir"
