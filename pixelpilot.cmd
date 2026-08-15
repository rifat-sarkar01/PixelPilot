@echo off
rem =====================================================================
rem  PixelPilot - interactive REPL (double-click or run from cmd)
rem  Launches the chat interface; type your edit request at the prompt.
rem  This is the one-click entry point: it also makes sure Ollama is
rem  running before handing off to pixelpilot (which auto-launches GIMP
rem  itself once the CLI starts - see src/pixelpilot/bridge/launcher.py).
rem =====================================================================
setlocal

rem Resolve relative to THIS script's location, so it works regardless of
rem where the repo/venv was checked out (it used to be hardcoded to the
rem original author's machine, e.g. D:\PixelPilot, which breaks for anyone
rem else - if that's still not right for your layout, edit PYTHON below).
set "SCRIPT_DIR=%~dp0"
set "PYTHON=%SCRIPT_DIR%.venv\Scripts\pixelpilot.exe"
if not exist "%PYTHON%" set "PYTHON=%USERPROFILE%\PixelPilot\.venv\Scripts\pixelpilot.exe"

if not exist "%PYTHON%" (
    where pixelpilot >nul 2>nul
    if not errorlevel 1 (
        call :ensure_ollama
        pixelpilot --editor gimp %*
        exit /b %errorlevel%
    )
    echo pixelpilot not found. Edit the PYTHON path at the top of this file to
    echo point at your PixelPilot .venv, e.g.:
    echo   set "PYTHON=C:\path\to\PixelPilot\.venv\Scripts\pixelpilot.exe"
    pause
    exit /b 1
)

call :ensure_ollama
"%PYTHON%" --editor gimp %*
exit /b %errorlevel%

:ensure_ollama
tasklist /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if not errorlevel 1 (
    rem already running
    exit /b 0
)
where ollama >nul 2>nul
if errorlevel 1 (
    echo [PixelPilot] Ollama was not found on PATH - if models fail to load,
    echo [PixelPilot] install it from https://ollama.com and re-run this file.
    exit /b 0
)
echo [PixelPilot] Starting Ollama in the background...
start "PixelPilot-Ollama" /min cmd /c "ollama serve"
rem Give it a moment to bind its port before the CLI's first request.
timeout /t 3 /nobreak >nul
exit /b 0
