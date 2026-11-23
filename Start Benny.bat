@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Benny-Launcher.ps1" -Action start
if errorlevel 1 pause

REM BENNY 110E-23E TAURI START
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-Process -Name 'openmimicry-desktop' -ErrorAction SilentlyContinue; if (-not $p) { Start-Process -FilePath '%~dp0apps\desktop\src-tauri\target\debug\openmimicry-desktop.exe' -WorkingDirectory '%~dp0' }"
