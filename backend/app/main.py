"""应用入口。

开发：`uvicorn app.main:app --reload --port 8000`
生产：`scripts/co.service`（Linux systemd）/ `scripts/start_backend.bat`（Windows 局域网）

单端口部署：设置 `FRONTEND_DIST` 指向前端 `dist/`（或用默认路径），
后端会同时托管 SPA，浏览器直接访问 `http://<host>:8000/` 即可，无需 Nginx。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, seed
from .db import init_db
from .routers import admin, auth, changeover, dicts, reports, wb
from .services.storage import SmbStorage
from .services.sync import (
    pending_count,
    smb_status,
    start_status_loop,
    start_sync_service,
    stop_status_loop,
    stop_sync_service,
)


def _storage_status() -> dict[str, Any]:
    try:
        return SmbStorage().health_check()
    except Exception as exc:  # 存储不可用不阻断启动，仅记录
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def resolve_frontend_dir() -> Path | None:
    """按 SERVE_FRONTEND 决定是否托管前端 dist；返回可用目录或 None。"""
    mode = (config.SERVE_FRONTEND or "auto").strip().lower()
    if mode in ("off", "0", "false", "no"):
        return None
    dist = Path(config.FRONTEND_DIST).expanduser()
    ok = (dist / "index.html").is_file()
    if mode in ("on", "1", "true", "yes") and not ok:
        print("[前端] SERVE_FRONTEND=on 但未找到 index.html：", dist)
    return dist if ok else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = config.validate_startup()
    for p in problems:
        print("[启动警告]", p)
    init_db()
    try:
        seed.run()
        print("[种子] 初始化完成（幂等）")
    except Exception as exc:
        print("[种子失败]", f"{type(exc).__name__}: {exc}")
    app.state.storage_status = _storage_status()
    print("[存储]", app.state.storage_status)
    fe = resolve_frontend_dir()
    app.state.frontend_dir = str(fe) if fe else None
    print("[前端]", f"托管 {fe}" if fe else "未托管（仅 API）")
    print(f"[服务] http://0.0.0.0:{config.APP_PORT}/  （单端口：API + 前端）")
    if config.SMB_HOST and config.SMB_SHARE:
        start_sync_service()
        print("[同步] 后台线程已启动（本地照片 -> SMB）")
    else:
        print("[同步] SMB 未配置，跳过后台同步服务")
    start_status_loop()
    print("[状态] SMB 连通性探测线程已启动")
    try:
        yield
    finally:
        stop_status_loop()
        stop_sync_service()


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 内网部署；如需收紧可改为白名单
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dicts.router)
app.include_router(changeover.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(wb.router)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "storage": getattr(app.state, "storage_status", {"ok": None}),
        "smb": smb_status(),
        "pending_sync": pending_count(),
        "frontend": getattr(app.state, "frontend_dir", None),
    }


# ---------------------------------------------------------------- 前端托管（可选）
_frontend = resolve_frontend_dir()
if _frontend is not None:
    _assets = _frontend / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """SPA 回退：命中静态文件则直出，否则交 index.html（前端 history 路由）。

        `/api/**` 不走此路由（各业务路由先注册，未命中的 API 路径显式 404）。
        """
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        root = _frontend.resolve()
        target = (root / full_path).resolve()
        if full_path and target.is_file() and root in target.parents:
            return FileResponse(target)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-store"})
