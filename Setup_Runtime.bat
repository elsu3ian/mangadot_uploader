@echo off
setlocal enabledelayedexpansion
title MangaDot Runtime & Dependency Setup
cd /d "%~dp0"

echo ============================================================
echo   MangaDot Uploader - Runtime & Dependency Provisioner
echo ============================================================
echo.

set "RUNTIME_DIR=%~dp0runtime"
set "VENV_DIR=%~dp0.venv"

:: Check if already set up
if exist "%RUNTIME_DIR%\python.exe" (
    echo [*] Found existing standalone runtime in 'runtime\'.
    set "TARGET_PY=%RUNTIME_DIR%\python.exe"
    goto :install_deps
)

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo [*] Found existing virtual environment in '.venv\'.
    set "TARGET_PY=%VENV_DIR%\Scripts\python.exe"
    goto :install_deps
)

:: Step 1: Check if system Python 3.12+ is installed
echo [*] Checking for system Python...
set "SYS_PY="

where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "SYS_PY=py -3.12"
    )
)

if "%SYS_PY%"=="" (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "SYS_PY=python"
        )
    )
)

if not "%SYS_PY%"=="" (
    echo [+] System Python 3.12+ detected: %SYS_PY%
    echo [*] Creating isolated virtual environment in '.venv\'...
    %SYS_PY% -m venv "%VENV_DIR%"
    if exist "%VENV_DIR%\Scripts\python.exe" (
        set "TARGET_PY=%VENV_DIR%\Scripts\python.exe"
        goto :install_deps
    ) else (
        echo [!] Failed to create venv. Falling back to portable runtime download...
    )
)

:: Step 2: Download portable Python embeddable package (~11 MB)
echo [*] No compatible Python found on system.
echo [*] Downloading official Python 3.12 64-bit portable runtime (11 MB)...
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
set "EMBED_ZIP=%TEMP%\python-3.12.8-embed-amd64.zip"
set "GET_PIP=%TEMP%\get-pip.py"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "Write-Host 'Downloading Python embed zip...'; " ^
    "(New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip', '%EMBED_ZIP%'); " ^
    "Write-Host 'Extracting to runtime...'; " ^
    "Expand-Archive -Path '%EMBED_ZIP%' -DestinationPath '%RUNTIME_DIR%' -Force; " ^
    "Remove-Item -Path '%EMBED_ZIP%' -Force;"

if not exist "%RUNTIME_DIR%\python.exe" (
    echo [ERROR] Failed to download or extract portable Python.
    echo Please check your internet connection or install Python manually.
    pause
    exit /b 1
)

:: Configure python312._pth to enable site-packages and app_bundle
echo [*] Configuring Python search paths...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pth = Join-Path '%RUNTIME_DIR%' 'python312._pth'; " ^
    "$lines = @('python312.zip', '.', 'Lib/site-packages', '../app_bundle', 'import site'); " ^
    "[System.IO.File]::WriteAllLines($pth, $lines);"

if not exist "%RUNTIME_DIR%\Lib\site-packages" mkdir "%RUNTIME_DIR%\Lib\site-packages"

:: Bootstrap pip
echo [*] Bootstrapping pip (~2 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "(New-Object System.Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py', '%GET_PIP%');"

"%RUNTIME_DIR%\python.exe" "%GET_PIP%" --no-warn-script-location
del "%GET_PIP%" >nul 2>&1

set "TARGET_PY=%RUNTIME_DIR%\python.exe"

:install_deps
echo.
echo ============================================================
echo   Installing / Upgrading Dependencies
echo ============================================================
echo [*] Target Python: %TARGET_PY%
echo [*] Upgrading pip...
"%TARGET_PY%" -m pip install --upgrade pip --no-warn-script-location

echo [*] Installing MangaDot requirements (GUI & CLI)...
"%TARGET_PY%" -m pip install -r requirements.txt -r app_bundle\requirements.txt --no-warn-script-location

if errorlevel 1 (
    echo.
    echo [ERROR] Some dependencies failed to install.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   SETUP COMPLETE!
echo.
echo   You can now launch MangaDot anytime using:
echo     - 'Start MangaDot GUI.bat' (Desktop GUI)
echo     - 'Run MangaDot Uploader.bat' (Terminal CLI)
echo ============================================================
echo.
pause
