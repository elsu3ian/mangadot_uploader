@echo off
title MangaDot Batch Uploader (CLI)
cd /d "%~dp0"

where uv >nul 2>&1
if not errorlevel 1 (
    uv run mangadot.py %*
    goto :done
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 mangadot.py %*
    goto :done
)

where python >nul 2>&1
if not errorlevel 1 (
    python mangadot.py %*
    goto :done
)

echo ============================================================
echo   ERROR: Neither uv nor Python was found on this PC.
echo.
echo   Install Python 3.12+ from https://www.python.org/downloads/
echo   or install uv via: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
echo ============================================================
echo.
pause
exit /b 1

:done
echo.
echo ============================================================
echo   Finished. Press any key to close this window.
echo ============================================================
pause >nul
