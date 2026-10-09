@echo off
REM ===========================================================================
REM  产线转产管理轻应用 · Windows 环境准备（一次性；可重复执行）
REM
REM  做四件事：① 建 venv 并装依赖 ② 生成 .env（含随机 JWT_SECRET）
REM            ③ 建库+灌种子 ④ 启动自检，并提示防火墙放行
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."
echo ==== 产线转产管理轻应用 · Windows 环境准备 ====

REM ---- 1. Python ----
where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 python，请安装 Python 3.11+ 并勾选 "Add to PATH"
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('python -V') do echo [1/6] %%v

REM ---- 2. venv + 依赖 ----
if not exist ".venv\Scripts\python.exe" (
  echo [2/6] 创建虚拟环境 .venv ...
  python -m venv .venv || (echo [错误] 创建 venv 失败 & pause & exit /b 1)
) else (
  echo [2/6] 复用已存在的 .venv
)
echo       安装依赖（首次约 1-3 分钟）...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo [错误] 依赖安装失败 & pause & exit /b 1)

REM ---- 3. .env ----
if not exist ".env" (
  if not exist ".env.example" (
    echo [错误] 缺少 .env.example，无法生成 .env
    pause & exit /b 1
  )
  copy /y ".env.example" ".env" >nul
  for /f "delims=" %%s in ('".venv\Scripts\python.exe" -c "import secrets;print(secrets.token_urlsafe(48))"') do set "NEWSECRET=%%s"
  REM 用 python 精确替换 JWT_SECRET 行并写入内网默认路径（避免 bat 转义地狱）
  ".venv\Scripts\python.exe" -c "import pathlib,os,re; p=pathlib.Path('.env'); t=p.read_text(encoding='utf-8'); t=re.sub(r'(?m)^JWT_SECRET=.*$','JWT_SECRET=%NEWSECRET%',t); p.write_text(t,encoding='utf-8')"
  echo [3/6] 已生成 .env（JWT_SECRET 已随机填充）
  echo       ！请编辑 .env 填写 SMB_HOST / SMB_SHARE / SMB_USER / SMB_PASSWORD 与管理员工号
  notepad .env
) else (
  echo [3/6] .env 已存在，保留不覆盖
)

REM ---- 4. .env 载入 ----
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  echo %%a | findstr /b /c:"#" >nul || (
    if not "%%a"=="" set "%%a=%%b"
  )
)
set PYTHONUNBUFFERED=1

REM ---- 5. 建库 + 种子 ----
echo [5/6] 建库并灌入字典（29 线体 / 11 工位 / 58 检查项）与种子管理员...
".venv\Scripts\python.exe" -c "from app.db import init_db; from app import seed; init_db(); seed.run()"

REM ---- 6. 自检 + 防火墙 ----
echo [6/6] 启动自检...
".venv\Scripts\python.exe" -m app.preflight

echo.
echo 放行防火墙端口 8000（局域网手机访问需要；失败通常是没以管理员运行 cmd）...
netsh advfirewall firewall show rule name="Changeover 8000" >nul 2>&1
if errorlevel 1 (
  netsh advfirewall firewall add rule name="Changeover 8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
  if errorlevel 1 (
    echo [提示] 自动放行失败，请以管理员身份执行：
    echo        netsh advfirewall firewall add rule name="Changeover 8000" dir=in action=allow protocol=TCP localport=8000
  ) else (
    echo [OK] 已放行 TCP 8000
  )
) else (
  echo [OK] 防火墙规则已存在
)

echo.
echo ==== 准备完成 ====
echo 启动服务： scripts\start_backend.bat
echo 本机访问： http://127.0.0.1:8000/
echo 手机访问： http://本机IP:8000/  ^(用 ipconfig 查看 IPv4 地址^)
pause
endlocal
