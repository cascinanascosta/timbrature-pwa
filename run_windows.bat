@echo off
setlocal EnableExtensions
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
