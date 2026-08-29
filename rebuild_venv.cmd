@echo off
rem =========================================================
rem  rebuild_venv.cmd  - Rebuild the PixelPilot virtual env
rem  Run this AFTER installing Python 3.12 from python.org
rem =========================================================
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

rem Try to find Python 3.12 (standard install locations)
set "PYTHON="
if exist "C:\Python312\python.exe"                             set "PYTHON=C:\Python312\python.exe"
if exist "C:\Program Files\Python312\python.exe"               set "PYTHON=C:\Program Files\Python312\python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if "%PYTHON%"=="" (
    echo ERROR: Could not find Python 3.12.
    echo Make sure you installed it from python.org with "Add to PATH" checked.
    echo Then run this script again.
    pause
    exit /b 1
)

echo Found Python: %PYTHON%
"%PYTHON%" --version

echo.
echo Removing old broken venv...
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"

echo Creating new venv...
"%PYTHON%" -m venv "%VENV_DIR%"
if errorlevel 1 (echo ERROR: venv creation failed & pause & exit /b 1)

echo Installing PixelPilot from source (editable install)...
"%VENV_DIR%\Scripts\pip" install -e "%SCRIPT_DIR%" --quiet
if errorlevel 1 (echo ERROR: pip install failed & pause & exit /b 1)

echo.
echo ============================================
echo  Done! Virtual env rebuilt successfully.
echo  You can now run:  pixelpilot.cmd
echo ============================================
pause
