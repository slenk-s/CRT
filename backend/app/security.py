"""口令哈希与 JWT（认证底层）。

口令直接用 bcrypt 库（不经过 passlib，规避 passlib 1.7.4 与 bcrypt≥4.1 的兼容问题）。
bcrypt 固有 72 字节上限：超出部分显式截断（与业界做法一致）。
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import bcrypt
import jwt

from . import config


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def create_token(emp_id: str, name: str, role: str) -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "sub": emp_id,
        "name": name,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + _dt.timedelta(hours=config.JWT_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
