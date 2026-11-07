@echo off
title MangaDot Uploader
cd /d "%~dp0"

set "PY_EXE="
if exist "%~dp0..\runtime\python.exe" (
    set PY_EXE="%~dp0..\runtime\python.exe"
) else if exist "%~dp0runtime\python.exe" (
    set PY_EXE="%~dp0runtime\python.exe"
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=py -3.12"
    ) else (
        where python >nul 2>&1
        if not errorlevel 1 (
            set "PY_EXE=python"
        )
    )
)

if not defined PY_EXE (
    echo ============================================================
    echo   ERROR: Python was not found on this computer.
    echo ============================================================
    pause
    exit /b 1
)

%PY_EXE% main.py %*
if errorlevel 1 pause
