@echo off
rem =====================================================================
rem  PixelPilot launcher  (pixelpilot.cmd)
rem  Double-click or run from cmd/PowerShell.
rem
rem  - With NO arguments  : shows an interactive setup menu so you can
rem    pick the editor (GIMP / Krita) and override the LLM models.
rem  - With arguments     : passes them straight through to the CLI
rem    (e.g.  pixelpilot.cmd --editor krita --vision-model llava:13b)
rem
rem  Run  pixelpilot.cmd --help  for the full list of CLI flags.
rem =====================================================================
setlocal EnableDelayedExpansion

rem ------------------------------------------------------------------
rem Locate the pixelpilot executable
rem   1. Standalone build  (dist\pixelpilot.exe  - built by PyInstaller)
rem   2. Venv-installed    (.venv\Scripts\pixelpilot.exe  - pip install -e .)
rem   3. System PATH       (pixelpilot installed globally)
rem ------------------------------------------------------------------
set "SCRIPT_DIR=%~dp0"
rem .venv (editable install from source) takes priority over the PyInstaller build
set "PIXELPILOT=%SCRIPT_DIR%.venv\Scripts\pixelpilot.exe"
if not exist "%PIXELPILOT%" set "PIXELPILOT=%USERPROFILE%\PixelPilot\.venv\Scripts\pixelpilot.exe"
if not exist "%PIXELPILOT%" set "PIXELPILOT=%SCRIPT_DIR%dist\pixelpilot.exe"

if not exist "%PIXELPILOT%" (
    where pixelpilot >nul 2>nul
    if not errorlevel 1 (
        set "PIXELPILOT=pixelpilot"
    ) else (
        echo.
        echo  ERROR: pixelpilot executable not found.
        echo  Make sure you ran:  pip install -e .
        echo  inside the PixelPilot virtual environment, then try again.
        echo.
        pause
        exit /b 1
    )
)

rem ------------------------------------------------------------------
rem If the user already passed arguments, skip the menu entirely
rem ------------------------------------------------------------------
if not "%~1"=="" goto :run_with_args

rem ------------------------------------------------------------------
rem Interactive setup menu
rem ------------------------------------------------------------------
cls
echo.
echo  ============================================================
echo   PixelPilot  -  AI-powered photo editor controller
echo  ============================================================
echo.

rem --- Editor choice ---
echo  Select your editor:
echo    [1] GIMP   (default port 10010)
echo    [2] Krita  (D:\Krita, default port 10020)
echo.
set /p "EDITOR_CHOICE=  Enter 1 or 2 [default: 1]: "
if "%EDITOR_CHOICE%"=="2" (
    set "PP_EDITOR=krita"
) else (
    set "PP_EDITOR=gimp"
)
echo.

rem --- Code model ---
echo  Code / coding LLM model:
echo    Press ENTER to use the value from config  (ollama.code_model)
echo    Or type a model name, e.g.  deepseek-coder:latest
echo.
set /p "CODE_MODEL=  Code model [ENTER = config default]: "

rem --- Vision model ---
echo.
echo  Vision LLM model:
echo    Press ENTER to use the value from config  (ollama.vision_model)
echo    Or type a model name, e.g.  llava:13b
echo.
set /p "VISION_MODEL=  Vision model [ENTER = config default]: "

rem --- Safety mode ---
echo.
echo  Safety / confirmation mode:
echo    [1] preview   - show script, ask before running  (default)
echo    [2] auto      - run without asking
echo    [3] dry-run   - show script, never run
echo    [4] strict    - extra checks + ask
echo.
set /p "MODE_CHOICE=  Enter 1-4 [default: 1]: "
if "%MODE_CHOICE%"=="2" set "PP_MODE=auto"
if "%MODE_CHOICE%"=="3" set "PP_MODE=dry-run"
if "%MODE_CHOICE%"=="4" set "PP_MODE=strict"
if not defined PP_MODE set "PP_MODE=preview"

rem --- Build the argument string ---
set "PP_ARGS=--editor !PP_EDITOR! --mode !PP_MODE!"
if not "!CODE_MODEL!"==""   set "PP_ARGS=!PP_ARGS! --model !CODE_MODEL!"
if not "!VISION_MODEL!"=="" set "PP_ARGS=!PP_ARGS! --vision-model !VISION_MODEL!"

echo.
echo  ============================================================
echo   Starting PixelPilot with: !PP_ARGS!
echo  ============================================================
echo.

call :ensure_ollama
"%PIXELPILOT%" !PP_ARGS!
exit /b %errorlevel%

rem ------------------------------------------------------------------
rem Non-interactive: pass all args straight through
rem ------------------------------------------------------------------
:run_with_args
call :ensure_ollama
"%PIXELPILOT%" %*
exit /b %errorlevel%

rem ------------------------------------------------------------------
rem Make sure Ollama is running
rem ------------------------------------------------------------------
:ensure_ollama
tasklist /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if not errorlevel 1 exit /b 0
where ollama >nul 2>nul
if errorlevel 1 (
    echo [PixelPilot] Ollama not found on PATH - models may fail to load.
    echo [PixelPilot] Install from https://ollama.com if needed.
    exit /b 0
)
echo [PixelPilot] Starting Ollama in the background...
start "PixelPilot-Ollama" /min cmd /c "ollama serve"
timeout /t 3 /nobreak >nul
exit /b 0
