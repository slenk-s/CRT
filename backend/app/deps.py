"""FastAPI 依赖：当前用户 / 管理员校验。"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_token
from .services.storage import SmbStorage, StorageError

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录")
    user = db.get(User, payload.get("sub"))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def get_storage() -> SmbStorage:
    """SMB 存储依赖；未配置或不可用时返回 503（而非 500）。"""
    try:
        return SmbStorage()
    except StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"照片存储不可用：{exc}") from exc


def ensure_owner_or_admin(record_owner: str, user: User) -> None:
    """仅本人或管理员可修改记录。"""
    if user.role == "admin" or record_owner == user.emp_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "只能操作本人创建的转产记录")
