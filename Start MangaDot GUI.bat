@echo off
title MangaDot Uploader GUI
cd /d "%~dp0"

:: 1. Check local standalone runtime
if exist "%~dp0runtime\python.exe" (
    "%~dp0runtime\python.exe" "app_bundle\main.py" %*
    goto :done
)

:: 2. Check local virtualenv
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "app_bundle\main.py" %*
    goto :done
)

:: 3. Check system Python with PySide6
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import PySide6" >nul 2>&1
    if not errorlevel 1 (
        py -3.12 "app_bundle\main.py" %*
        goto :done
    )
)

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import PySide6" >nul 2>&1
    if not errorlevel 1 (
        python "app_bundle\main.py" %*
        goto :done
    )
)

:: 4. Auto-setup prompt if environment is missing
echo ============================================================
echo   MangaDot Uploader GUI - First-Time Setup Required
echo ============================================================
echo.
echo   A Python environment with GUI dependencies (PySide6) was
echo   not found on this PC.
echo.
echo   Would you like to automatically provision a self-contained
echo   runtime and install all dependencies now?
echo   (Takes ~30 seconds, requires no admin rights)
echo.
set /p "DO_SETUP=Run automatic setup now? [Y/N]: "
if /i "%DO_SETUP%"=="Y" (
    call "%~dp0Setup_Runtime.bat"
    if exist "%~dp0runtime\python.exe" (
        "%~dp0runtime\python.exe" "app_bundle\main.py" %*
        goto :done
    )
    if exist "%~dp0.venv\Scripts\python.exe" (
        "%~dp0.venv\Scripts\python.exe" "app_bundle\main.py" %*
        goto :done
    )
)

:done
