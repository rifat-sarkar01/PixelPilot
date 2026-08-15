# Starts GIMP with the PixelPilot bridge auto-invoked.
#
# NOTE: as of the latest release, `pixelpilot --editor gimp` does this
# automatically (finds GIMP, deploys the plugin, launches it, and waits for
# the bridge) - you no longer need to run this script by hand first. It's
# kept as a manual fallback for machines where auto-detection can't find
# GIMP (pass -GimpDir explicitly in that case).
#
# Usage:  powershell -ExecutionPolicy Bypass -File start_gimp_bridge.ps1 [-GimpDir "C:\Program Files\GIMP 2"]
#
# Why the batch arg: GIMP 2.10 runs python-fu plug-ins in short-lived processes,
# so the bridge must be started by *invoking* the registered procedure. That
# spawns a python.exe that hosts the socket (port 10010) until GIMP exits.
#
# Why PYTHONDONTWRITEBYTECODE: Python 2.7 writes pixelpilot_plugin.pyc next to
# the script; GIMP then tries to exec the .pyc as a plug-in and fails with
# "Exec format error", which breaks python-fu registration on later launches.

param(
    [string]$GimpDir = "",
    [int]$WaitSeconds = 120
)

$ErrorActionPreference = "Stop"

$pluginSrc = Join-Path $PSScriptRoot "plugin.py"
$pluginDir = Join-Path $env:APPDATA "GIMP\2.10\plug-ins"
$pluginPy  = Join-Path $pluginDir "pixelpilot_plugin.py"
$pluginPyc = Join-Path $pluginDir "pixelpilot_plugin.pyc"

New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
Copy-Item -LiteralPath $pluginSrc -Destination $pluginPy -Force
Remove-Item -LiteralPath $pluginPyc -ErrorAction SilentlyContinue

if ($GimpDir -eq "") {
    # Auto-detect: prefer a plain "GIMP 2" folder, else the first
    # version-numbered "GIMP*" folder under Program Files (x86 too).
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
    $found = $null
    foreach ($root in $roots) {
        $plain = Join-Path $root "GIMP 2"
        if (Test-Path (Join-Path $plain "bin\gimp-2.10.exe")) { $found = $plain; break }
        $versioned = Get-ChildItem -Path $root -Filter "GIMP*" -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName "bin\gimp-2.10.exe") } |
            Select-Object -First 1
        if ($versioned) { $found = $versioned.FullName; break }
    }
    if (-not $found) {
        Write-Error "Could not auto-detect a GIMP 2.10 install. Pass -GimpDir explicitly, e.g. -GimpDir 'C:\Program Files\GIMP 2'."
    }
    $GimpDir = $found
}

$gimpExe = Join-Path $GimpDir "bin\gimp-2.10.exe"
if (-not (Test-Path $gimpExe)) { Write-Error "GIMP not found at $gimpExe" }

$env:PYTHONDONTWRITEBYTECODE = "1"

# Kill old GIMP and any stale bridge process still holding port 10010 (the
# bridge python process survives GIMP shutdown because it blocks forever).
Get-Process -Name "gimp-2.10" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$stale = netstat -ano | Select-String ":10010.*LISTENING" | ForEach-Object {
    ($_.ToString().Trim() -split "\s+")[-1]
} | Sort-Object -Unique
foreach ($procId in $stale) {
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# NOTE: pass the batch expression as ONE pre-quoted string. Start-Process
# splits array arguments on spaces, corrupting the parenthesised script-fu
# expression and silently breaking the invocation.
Start-Process -FilePath $gimpExe -ArgumentList "-b `"(python-fu-pixelpilot-bridge RUN-NONINTERACTIVE)`""

Write-Host "Waiting for bridge on 127.0.0.1:10010 ..."
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    $listener = netstat -ano | Select-String ":10010.*LISTENING"
    if ($listener) {
        Write-Host "Bridge is UP." -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 5
}
Write-Error "Bridge did not come up within $WaitSeconds s. Check $env:APPDATA\GIMP\2.10\plug-ins\pixelpilot_plugin.py"
