from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


DEFAULTS = {
    "APP_HOST": "0.0.0.0",
<<<<<<< HEAD
    "APP_PORT": "8001",
=======
    "APP_PORT": "8000",
>>>>>>> 9d0a5a9 (初始化 PCC v1.1 项目)
    "PYTHONUNBUFFERED": "1",
    "PYTHONIOENCODING": "utf-8",
}


def read_env_file(env_path: Path) -> int:
    if not env_path.exists():
        print(f"[.env] not found: {env_path}", file=sys.stderr)
        return 0

    print(f"[.env] loading {env_path}")
    count = 0
    for lineno, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"[.env] skip line {lineno}: missing '=' -> {line!r}", file=sys.stderr)
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        count += 1

    print(f"[.env] loaded {count} variables")
    return count


def is_port_available(port: int, host: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) != 0


def resolve_port(preferred: int, host: str, attempts: int = 20) -> int:
    if host in {"0.0.0.0", "127.0.0.1"}:
        check_host = "127.0.0.1"
    else:
        check_host = host

    for offset in range(attempts):
        port = preferred + offset
        if port > 65535:
            break
        if is_port_available(port, check_host):
            if port != preferred:
                print(f"[port] {preferred} is busy; using {port}")
            return port
    raise RuntimeError(f"no free port found from {preferred} to {min(65535, preferred + attempts - 1)}")


def main() -> int:
    env_path = Path(os.environ.get("APP_ENV_FILE") or Path.cwd() / ".env")
    read_env_file(env_path)

    for key, value in DEFAULTS.items():
        if not (os.environ.get(key) or "").strip():
            os.environ[key] = value

    host = os.environ.get("APP_HOST", DEFAULTS["APP_HOST"])
    try:
        port = resolve_port(int(os.environ.get("APP_PORT", DEFAULTS["APP_PORT"])), host)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print("[startup] uvicorn app.main:app")
    print(f"[startup] local http://127.0.0.1:{port}/")
    print("[startup] press Ctrl+C to stop")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        check=False,
        cwd=str(Path.cwd()),
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())