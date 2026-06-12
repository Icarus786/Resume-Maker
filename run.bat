@echo off
REM Start the Resume Maker web app on http://127.0.0.1:8000
REM Run check_env.py first if you haven't verified your setup yet:
REM   python check_env.py

cd /d "%~dp0"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
