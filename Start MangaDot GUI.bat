@echo off
title MangaDot Uploader GUI
cd /d "%~dp0app_bundle"

where python >nul 2>&1
if not errorlevel 1 (
    python main.py %*
    goto :done
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 main.py %*
    goto :done
)

echo ============================================================
echo   ERROR: Python was not found on your system.
echo   Please install Python 3.12+ from https://www.python.org/
echo   and run: pip install -r app_bundle\requirements.txt
echo ============================================================
pause
exit /b 1

:done
