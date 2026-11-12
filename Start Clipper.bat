@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo One-time setup is needed. Follow the Local dashboard setup in README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
