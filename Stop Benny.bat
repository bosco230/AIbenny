@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Benny-Launcher.ps1" -Action stop
exit /b %errorlevel%
