@echo off
rem =====================================================================
rem  PixelPilot - Start GIMP with the bridge plugin (double-click or cmd)
rem  Wraps start_gimp_bridge.ps1 so it runs under both cmd.exe and Explorer.
rem  Optional: pass -GimpDir "path" and -WaitSeconds N.
rem =====================================================================
setlocal
set "SCRIPT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_gimp_bridge.ps1" %*

if errorlevel 1 (
    echo.
    echo Bridge did not start. See the messages above.
    echo Check that GIMP 2.10 is installed and that the plugin deployed to
    echo %APPDATA%\GIMP\2.10\plug-ins\pixelpilot_plugin.py
    pause
    exit /b 1
)

echo.
echo Done. You can now run:  python -m pixelpilot --editor gimp
pause
exit /b 0
