@echo off
cd /d "%~dp0"
if not exist ".runtime\venv\Scripts\python.exe" (
  echo Please run Start.cmd first.
  pause
  exit /b 1
)
".runtime\venv\Scripts\python.exe" -B -X utf8 "scripts\esj_login.py"
pause
