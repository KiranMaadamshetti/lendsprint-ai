@echo off
cd /d "%~dp0"
echo Stopping any old LendSprint server on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >NUL 2>&1
echo Installing requirements...
python -m pip install -q -r requirements.txt
start "" http://localhost:8000
echo Starting LendSprint on http://localhost:8000  (keep this window open)
python -m uvicorn backend.main:app --port 8000
pause
