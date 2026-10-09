@echo off
REM ===========================================================================
REM  Changeover app - Windows quick start
REM  Usage: from backend directory, run scripts\start_backend.bat
REM  This script intentionally uses a tiny Python loader for .env so Chinese
REM  comments, URLs containing '=' and special characters do not break CMD.
REM ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0.."

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\Python311.exe" (
  set "PYTHON_EXE=.venv\Scripts\Python311.exe"
) else if exist "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\Python311.exe" (
  set "PYTHON_EXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\Python311.exe"
)

if not defined PYTHON_EXE (
  echo [ERROR] Python executable not found.
  echo [ERROR] Expected .venv\Scripts\python.exe, .venv\Scripts\Python311.exe, or Python 3.11 on this machine.
  pause
  exit /b 1
)

if not exist "%~dp0load_env.py" (
  echo [ERROR] scripts\load_env.py not found.
  pause
  exit /b 1
)

echo ============================================
echo  Changeover app quick start
echo  Python: %PYTHON_EXE%
echo  Env:    .env
echo  Backend default port: 8001 for frontend/backend dev split.
echo  If that port is busy, the script picks the next free port.
echo  Press Ctrl+C to stop.
echo ============================================

"%PYTHON_EXE%" "%~dp0load_env.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo [stopped] exit code %EXIT_CODE%
  pause
  exit /b %EXIT_CODE%
)
endlocal