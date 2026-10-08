@echo off
REM Builds dist\RoliAdPoster.exe (GUI), dist\RoliAdPosterCLI.exe (console)
REM and, if Inno Setup 6 is installed, dist\RolimonsAdPosterSetup.exe (installer).
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv || goto :fail
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller || goto :fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --collect-data sv_ttk ^
    --icon assets\icon.ico --add-data "assets\icon.ico;assets" --name RoliAdPoster gui.py || goto :fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --console ^
    --icon assets\icon.ico --name RoliAdPosterCLI main.py || goto :fail

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
for /f "delims=" %%v in ('.venv\Scripts\python -c "import roliposter; print(roliposter.__version__)"') do set "VER=%%v"
if exist "%ISCC%" (
    "%ISCC%" /Q /DAppVersion=%VER% installer.iss || goto :fail
    echo Built: dist\RolimonsAdPosterSetup.exe ^(share this one^)
) else (
    echo Inno Setup 6 not found; skipped the installer. Install it with: winget install JRSoftware.InnoSetup
)
echo Built: dist\RoliAdPoster.exe and dist\RoliAdPosterCLI.exe
exit /b 0
:fail
echo Build failed.
exit /b 1
