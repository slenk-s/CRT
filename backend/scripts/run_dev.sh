#!/usr/bin/env bash
# 内网服务器态启动（Linux）。首次运行会自动建表 + 灌种子数据。
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ ! -d .venv ]; then
  echo "[1/3] 创建虚拟环境..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "[2/3] 安装依赖..."
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo "[3/3] 启动 uvicorn ..."
if [ -f .env ]; then
  set -a; source .env; set +a
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
