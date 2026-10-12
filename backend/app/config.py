"""转产测试追溯 CRT · 后端配置（只读环境变量，不写死任何密钥/内网地址）。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int((os.environ.get(key) or "").strip() or default)
    except ValueError:
        return default


# ---- 应用 ----
APP_NAME = "转产测试追溯 CRT"
APP_VERSION = "0.1.0"

# ---- 服务绑定（部署用；Windows 局域网/服务器均可） ----
APP_HOST = _env("APP_HOST", "0.0.0.0")
APP_PORT = _env_int("APP_PORT", 8000)

# ---- 数据库（SQLite 元数据；照片在 SMB，不入库） ----
DB_PATH = _env("DB_PATH", str(BASE_DIR / "data" / "app.db"))

# ---- 认证 ----
JWT_SECRET = _env("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = _env_int("JWT_EXPIRE_HOURS", 12)

# ---- SMB 照片存储 ----
SMB_HOST = _env("SMB_HOST", "")
SMB_SHARE = _env("SMB_SHARE", "")
SMB_ROOT = _env("SMB_ROOT", "")       # 共享内子路径，如 slenk_\\FA_ROOT
SMB_USER = _env("SMB_USER", "")       # 可空=匿名（不建议生产）
SMB_PASSWORD = _env("SMB_PASSWORD", "")
SMB_DOMAIN = _env("SMB_DOMAIN", "")   # 可选；会拼成 DOMAIN\user

# ---- 本地照片临时目录（SMB 不可用时的降级）----
LOCAL_PHOTO_DIR = _env("LOCAL_PHOTO_DIR", str(BASE_DIR / "data" / "local_photos"))
LOCAL_PHOTO_SYNC_INTERVAL = _env_int("LOCAL_PHOTO_SYNC_INTERVAL", 30)  # 秒

# ---- 上传限制 ----
MAX_IMAGE_MB = _env_int("MAX_IMAGE_MB", 10)
MAX_IMAGE_EDGE = _env_int("MAX_IMAGE_EDGE", 1920)   # 客户端压缩长边上限（服务端兜底校验）

# ---- 草稿清理（未提交草稿保留天数；正式记录永不自动删） ----
DRAFT_TTL_DAYS = _env_int("DRAFT_TTL_DAYS", 7)

# ---- 前端静态资源（后端可直接托管 SPA，实现单端口部署，免 Nginx）----
FRONTEND_DIST = _env("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))
SERVE_FRONTEND = _env("SERVE_FRONTEND", "auto")   # auto（有 index.html 则托管）| on | off

# ---- wb_mail / MES 端点（与 wb-mail 同名约定；启动时校验） ----
WB_ENDPOINT_KEYS = ("TIOT_URL", "MID_API_URL", "ODF_URL", "MES_API_BASE",
                    "MES_DOMAIN", "MES_REFERER")
WB_QUERY_REQUIRED = ("TIOT_URL", "MID_API_URL")      # 按批次查询必需
WB_BOM_REQUIRED = ("TIOT_URL",)                      # 按 BOM 查询必需

# ---- wb_mail / MES 端点（供 WB 查询与 MES 数据使用） ----
TIOT_URL = _env("TIOT_URL", "")
MID_API_URL = _env("MID_API_URL", "")
ODF_URL = _env("ODF_URL", "")
MES_API_BASE = _env("MES_API_BASE", "")
MES_DOMAIN = _env("MES_DOMAIN", "")
MES_REFERER = _env("MES_REFERER", "")

# ---- WB 参数查询数据源（阶段 6）----
WB_SOURCE = _env("WB_SOURCE", "auto")        # off | mock | http | mes | auto
WB_MAIL_PATH = _env("WB_MAIL_PATH", "")      # wb_mail 包所在目录（需加入 sys.path 时填）
WB_BY_BATCH_URL = _env("WB_BY_BATCH_URL", "")
WB_BY_BOM_URL = _env("WB_BY_BOM_URL", "")

# ---- 种子管理员（首次登录强制改密） ----
SEED_ADMIN_EMP_ID = _env("SEED_ADMIN_EMP_ID", "")
SEED_ADMIN_NAME = _env("SEED_ADMIN_NAME", "")
SEED_ADMIN_PASSWORD = _env("SEED_ADMIN_PASSWORD", "")


def missing_required(keys: tuple[str, ...] = ()) -> list[str]:
    """返回缺失的环境变量名（用于启动校验）。"""
    return [k for k in keys if not (os.environ.get(k) or "").strip()]


def validate_startup() -> list[str]:
    """启动校验：返回问题清单（空=通过）。"""
    problems: list[str] = []
    if not JWT_SECRET:
        problems.append("JWT_SECRET 未配置（用于签发登录 token）")
    if not SMB_HOST or not SMB_SHARE:
        problems.append("SMB_HOST / SMB_SHARE 未配置（照片存储不可用）")
    return problems
