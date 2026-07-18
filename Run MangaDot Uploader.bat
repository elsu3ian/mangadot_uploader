@echo off
title MangaDot Batch Uploader
cd /d "%~dp0"

py -3.12 -V >nul 2>&1
if errorlevel 1 (
    echo ============================================================
    echo   ERROR: Python 3.12 was not found on this PC.
    echo.
    echo   Install it from https://www.python.org/downloads/
    echo   During install, make sure "Add python.exe to PATH" is checked.
    echo ============================================================
    echo.
    pause
    exit /b 1
)

py -3.12 mangadot.py %*

echo.
echo ============================================================
echo   Upload finished. Press any key to close this window.
echo ============================================================
pause >nul
