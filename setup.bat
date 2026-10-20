@echo off
REM One-time setup on Windows. Needs Python 3.11 or newer (python.org, tick "Add python.exe to PATH").
cd /d "%~dp0"
echo Creating a private Python environment in .venv ...
python -m venv .venv
if errorlevel 1 (
  echo Python was not found. Install Python 3.11+ from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check the internet connection and run setup.bat again.
  pause
  exit /b 1
)
echo.
echo Setup finished. Double-click run_demo.bat to start the dashboard.
pause
