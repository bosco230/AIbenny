$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

$Launcher = Join-Path $Root "Benny-Launcher.ps1"
$Tauri = Join-Path $Root "apps\desktop\src-tauri\target\debug\openmimicry-desktop.exe"

if (-not (Test-Path $Launcher)) {
    throw "Benny-Launcher.ps1 not found"
}

if (-not (Test-Path $Tauri)) {
    throw "Benny desktop executable not found"
}

# Start the existing backend/frontend/Ollama launcher directly.
# No extra CMD /k window is created.

& $Launcher -Action start

if (-not $?) {
    throw "Benny launcher failed"
}

# Preserve the original desktop launch behaviour.

$DesktopProcess = Get-Process `
    -Name "openmimicry-desktop" `
    -ErrorAction SilentlyContinue

if (-not $DesktopProcess) {
    Start-Process `
        -FilePath $Tauri `
        -WorkingDirectory $Root
}