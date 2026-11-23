@echo off
REM OpenMimicry — run the FastAPI backend on :8000.
setlocal enableextensions
REM Benny: use IPv4 for LiteLLM Ollama model information requests.
set "OLLAMA_API_BASE=http://127.0.0.1:11434"

REM Load Azure Speech credentials from Windows user environment.
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v AZURE_SPEECH_KEY 2^>nul ^| findstr /i "AZURE_SPEECH_KEY"') do set "AZURE_SPEECH_KEY=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v AZURE_SPEECH_REGION 2^>nul ^| findstr /i "AZURE_SPEECH_REGION"') do set "AZURE_SPEECH_REGION=%%B"

for %%I in ("%~dp0\..\..") do set "REPO_ROOT=%%~fI"
pushd "%REPO_ROOT%" || exit /b 1
if defined OPENMIMICRY_VENV (
    for %%I in ("%OPENMIMICRY_VENV%") do set "VENV=%%~fI"
) else (
    set "VENV=%REPO_ROOT%\.venv"
)
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" (
    echo OpenMimicry Python environment not found: %PY%
    echo Run scripts\win\install.bat from this OpenMimicry checkout first.
    popd
    exit /b 1
)

REM Real Windows TTS may generate COM bindings under .venv on first use.
REM The Uvicorn reloader must be disabled for that launch or WatchFiles will
REM restart the backend halfway through the reply and drop every WebSocket.
if /i "%~1"=="--reload" goto :reload

"%PY%" -m uvicorn openmimicry_backend.main:app --port 8000
set "BACKEND_ERROR=%errorlevel%"
popd
exit /b %BACKEND_ERROR%

:reload
"%PY%" -m uvicorn openmimicry_backend.main:app --reload --port 8000
set "BACKEND_ERROR=%errorlevel%"
popd
exit /b %BACKEND_ERROR%
