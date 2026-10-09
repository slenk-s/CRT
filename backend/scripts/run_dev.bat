@echo off
REM 本机测试态启动（Windows）。首次运行会自动建表 + 灌种子数据。
chcp 65001 >nul
cd /d %~dp0..\..
if not exist .venv (
  echo [1/3] 创建虚拟环境...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [2/3] 安装依赖...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if exist .env (
  echo [3/3] 已发现 .env，启动 uvicorn ...
) else (
  echo [3/3] 未发现 .env，将用环境变量/默认值启动（SMB 未配置时照片功能不可用）
)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
