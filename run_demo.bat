@echo off
REM Starts the SecTwin dashboard at http://localhost:8600 and opens it in the browser.
REM Optional: set ANTHROPIC_API_KEY before running to enable live assessments without a GPU.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://localhost:8600
python -m uvicorn sectwin.api.server:app --host 127.0.0.1 --port 8600
pause
