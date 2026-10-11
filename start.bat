@echo off
setlocal EnableExtensions
title PCC v1.1 Launcher
cd /d "%~dp0"

:menu
cls
echo ============================================
echo   PCC v1.1 Launcher
echo ============================================
echo   [1] Dual-port mode
echo       Backend : http://127.0.0.1:8001
echo       Frontend: http://127.0.0.1:5173
echo   [2] Single-port mode
echo       Backend + Frontend: http://127.0.0.1:8000
echo   [q] Quit
echo ============================================
choice /c 12q /n /m "Select option "
if errorlevel 3 goto :eof
if errorlevel 2 goto :single
goto :dual

:dual
echo.
echo Starting dual-port mode...
call :check_port 8001 backend
if errorlevel 1 goto :menu
call :check_port 5173 frontend
if errorlevel 1 goto :menu

echo Creating helper scripts...
(
  echo @echo off
  echo title PCC-backend-8001
  echo cd /d "%~dp0backend"
  echo ".venv\Scripts\Python311.exe" scripts\start_dual.py
  echo pause
) > _run_be.bat
(
  echo @echo off
  echo title PCC-frontend-5173
  echo cd /d "%~dp0frontend"
  echo call npm run dev
  echo pause
) > _run_fe.bat

start "PCC-backend-8001" cmd /k _run_be.bat
start "PCC-frontend-5173" cmd /k _run_fe.bat
echo Opening 2 windows. Cleaning helper scripts in 6s...
timeout /t 6 /nobreak >nul
del _run_be.bat _run_fe.bat 2>nul
goto :eof

:single
echo.
echo Starting single-port mode...
call :check_port 8000 backend-single
if errorlevel 1 goto :menu
if not exist "frontend\dist\index.html" (
    echo Frontend not built. Running npm run build...
    pushd "%~dp0frontend"
    call npm run build
    popd
)
echo Serving http://127.0.0.1:8000
pushd "%~dp0backend"
".venv\Scripts\Python311.exe" scripts\load_env.py
popd
echo Stopped.
echo.
goto :menu

:check_port
set port=%~1
set label=%~2
echo Checking port %port% %label%...
netstat -ano -p tcp | findstr ":%port% " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo Port %port% is occupied:
    netstat -ano -p tcp | findstr ":%port% " | findstr "LISTENING"
    set /p kill=Kill process? y/N  :
    if /i not "%kill%"=="y" (
        echo Aborting.
        exit /b 1
    )
    for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr ":%port% " ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>nul
    echo Killed.
)
exit /b 0
