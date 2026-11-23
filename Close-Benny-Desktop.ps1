$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExpectedExe = Join-Path $Root "apps\desktop\src-tauri\target\debug\openmimicry-desktop.exe"

Write-Host "BENNY 110E-24 - CLOSING DESKTOP"

# Close only the known Benny desktop executable
$Processes = Get-CimInstance Win32_Process -Filter "Name = 'openmimicry-desktop.exe'"

foreach ($Process in $Processes) {
    if ($Process.ExecutablePath -and
        [string]::Equals(
            $Process.ExecutablePath,
            $ExpectedExe,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {

        Write-Host "Closing Benny desktop PID $($Process.ProcessId)"
        Stop-Process -Id $Process.ProcessId -ErrorAction SilentlyContinue
    }
}

# Stop services managed by the existing launcher
$StopBat = Join-Path $Root "Stop Benny.bat"

if (Test-Path $StopBat) {
    & $StopBat
}

Write-Host "Benny desktop close completed."
Write-Host "Ollama is left running."