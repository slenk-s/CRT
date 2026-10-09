@echo off
REM ===========================================================================
REM  产线转产管理轻应用 · Windows 开机自启（可选，适合长期开机的测试机）
REM
REM  用计划任务（schtasks）在开机时启动服务，无需第三方工具（NSSM）。
REM  需要【以管理员身份】运行本脚本。
REM
REM   安装： scripts\install_autostart_windows.bat
REM   卸载： scripts\install_autostart_windows.bat remove
REM   立即执行： schtasks /Run /TN ChangeoverBackend
REM ===========================================================================
setlocal
cd /d "%~dp0.."
set TASK=ChangeoverBackend

net session >nul 2>&1
if errorlevel 1 (
  echo [错误] 请右键"以管理员身份运行"本脚本（创建计划任务需要管理员权限）
  pause & exit /b 1
)

if /i "%~1"=="remove" (
  schtasks /Delete /TN "%TASK%" /F >nul 2>&1 && echo [OK] 已移除开机自启任务 || echo [提示] 任务不存在或删除失败
  pause & exit /b 0
)

set BAT=%~dp0start_backend.bat
schtasks /Create /TN "%TASK%" /TR "\"%BAT%\"" /SC ONSTART /RL HIGHEST /F >nul 2>&1
if errorlevel 1 (
  echo [错误] 创建计划任务失败
  pause & exit /b 1
)
echo [OK] 已创建开机自启任务：%TASK%
echo      立即启动： schtasks /Run /TN %TASK%
echo      查看状态： schtasks /Query /TN %TASK% /V /FO LIST
echo      停止任务： schtasks /End /TN %TASK%
echo.
echo [提示] 日志在控制台窗口；如需长期后台运行，建议同时把
echo        start_backend.bat 的输出重定向到文件（自行修改该 bat）。
pause
endlocal
