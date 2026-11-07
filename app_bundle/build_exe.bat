@echo off
rem Builds dist\MangaDot Uploader.exe (single file, no console window).
rem Uses a throwaway venv so only requirements.txt + PyInstaller are present
rem (PyInstaller refuses to build if more than one Qt binding is installed).
cd /d "%~dp0"

if not exist ".venv-build\Scripts\activate.bat" (
    py -3.12 -m venv .venv-build || goto :fail
)
call ".venv-build\Scripts\activate.bat" || goto :fail

python -m pip install --upgrade pip || goto :fail
pip install -r requirements.txt pyinstaller || goto :fail

pyinstaller --noconfirm --clean --noupx --onefile --windowed ^
  --name "MangaDot Uploader" ^
  --icon "mangadot_app\assets\favicon.ico" ^
  --add-data "mangadot_app\assets;mangadot_app\assets" ^
  --add-data "pingo.exe;." ^
  --collect-all mozjpeg_lossless_optimization ^
  --collect-all rookiepy ^
  main.py || goto :fail

echo.
echo Done: dist\MangaDot Uploader.exe
pause
exit /b 0

:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
