@echo off
title MangaDot Batch Uploader (CLI)
cd /d "%~dp0"

:: 1. Check uv
where uv >nul 2>&1
if not errorlevel 1 (
    uv run mangadot.py %*
    goto :done
)

:: 2. Check local standalone runtime
if exist "%~dp0runtime\python.exe" (
    "%~dp0runtime\python.exe" mangadot.py %*
    goto :done
)

:: 3. Check local virtualenv
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" mangadot.py %*
    goto :done
)

:: 4. Check system Python
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

:: 5. Auto-setup prompt if environment is missing
echo ============================================================
echo   MangaDot Uploader CLI - First-Time Setup Required
echo ============================================================
echo.
echo   Neither uv nor Python was found on this PC.
echo.
echo   Would you like to automatically provision a self-contained
echo   runtime and install all dependencies now?
echo   (Takes ~30 seconds, requires no admin rights)
echo.
set /p "DO_SETUP=Run automatic setup now? [Y/N]: "
if /i "%DO_SETUP%"=="Y" (
    call "%~dp0Setup_Runtime.bat"
    if exist "%~dp0runtime\python.exe" (
        "%~dp0runtime\python.exe" mangadot.py %*
        goto :done
    )
    if exist "%~dp0.venv\Scripts\python.exe" (
        "%~dp0.venv\Scripts\python.exe" mangadot.py %*
        goto :done
    )
)

:done
echo.
echo ============================================================
echo   Finished. Press any key to close this window.
echo ============================================================
pause >nul
