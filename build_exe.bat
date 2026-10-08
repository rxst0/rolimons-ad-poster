@echo off
REM Builds dist\RoliAdPoster.exe (GUI) and dist\RoliAdPosterCLI.exe (console).
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv || goto :fail
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller || goto :fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --collect-data sv_ttk --name RoliAdPoster gui.py || goto :fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --console --name RoliAdPosterCLI main.py || goto :fail
echo.
echo Built: dist\RoliAdPoster.exe (share this one) and dist\RoliAdPosterCLI.exe
exit /b 0
:fail
echo Build failed.
exit /b 1
