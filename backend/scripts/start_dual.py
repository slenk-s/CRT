# 双端开发模式：加载 .env 并以 APP_PORT=8001 启动后端
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # backend/
env_path = ROOT / ".env"
if env_path.exists():
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
    print(f"[.env] loaded from {env_path}")

# 双端模式固定 8001（前端 vite 代理指向该端口）
os.environ["APP_HOST"] = os.environ.get("APP_HOST", "0.0.0.0")
os.environ["APP_PORT"] = os.environ.get("APP_PORT", "8001")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUNBUFFERED"] = "1"

print(f"[start] uvicorn app.main:app --host {os.environ['APP_HOST']} --port {os.environ['APP_PORT']} --reload")
sys.exit(subprocess.run(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", os.environ["APP_HOST"],
     "--port", os.environ["APP_PORT"],
     "--reload"],
    cwd=str(ROOT),
).returncode)
